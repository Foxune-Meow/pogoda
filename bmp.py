#!/usr/bin/env python3
"""
Stacja Pogodowa BMP280 – wersja produkcyjna dla Raspberry Pi
Pomiar co 5 minut, commit Git co 15 minut.

Wymagania:
    pip install adafruit-circuitpython-bmp280 gitpython

Konfiguracja tokena GitHub (OBOWIĄZKOWO przed uruchomieniem):
    export GITHUB_TOKEN="ghp_TwójToken"
    # lub wpisz w pliku serwisu systemd (patrz stacja-pogodowa.service)

Uruchomienie jako serwis:
    sudo cp stacja-pogodowa.service /etc/systemd/system/
    sudo systemctl enable --now stacja-pogodowa.service
"""

import os
import sys
import time
import socket
import datetime
import csv
import git
import board
import busio
import adafruit_bmp280
import logging
import threading
import shutil
import fcntl
from logging.handlers import RotatingFileHandler

# ─────────────────────────────────────────────────────────────────────────────
#  KONFIGURACJA
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR          = "/home/foxune/pogoda/pogoda"
CSV_PREFIX        = "dane"          # pliki: dane_2026-07.csv, dane_2026-08.csv …
BMP280_ADDRESS    = 0x76            # adres I2C czujnika
TEMP_CORRECTION   = -2.0           # korekta temperatury [°C]
MEASUREMENT_SEC   = 300            # interwał pomiaru [s]  = 5 min
COMMIT_EVERY_N    = 3              # commit co N pomiarów  = 15 min
GC_EVERY_N        = 2016           # git gc co 7 dni (7 × 24 × 12 pomiarów)
MIN_DISK_MB       = 150            # krytyczny próg wolnego miejsca [MB]
WARN_DISK_MB      = 400            # próg ostrzeżenia [MB]
MAX_SENSOR_ERRORS = 5              # błędy I2C → reinicjalizacja czujnika
MAX_PUSH_ERRORS   = 10             # błędy push → wstrzymaj sync (reset po 24h)
PUSH_TIMEOUT_SEC  = 90            # maks. czas git push [s]
LOG_FILE          = os.path.join(BASE_DIR, "bmp.log")
LOG_MAX_BYTES     = 5 * 1024 * 1024   # 5 MB na plik logu
LOG_BACKUP_COUNT  = 3                  # trzymaj 3 stare pliki logu
FIXED_CSV_PATH    = os.path.join(BASE_DIR, "dane.csv")  # stały plik zbiorczy

# Token GitHub ze zmiennej środowiskowej (NIE wpisuj tokena bezpośrednio w kodzie)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGER – rotujący plik + konsola
# ─────────────────────────────────────────────────────────────────────────────
def _setup_logger() -> logging.Logger:
    os.makedirs(BASE_DIR, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    log = logging.getLogger("stacja")
    log.setLevel(logging.INFO)
    log.addHandler(file_handler)
    log.addHandler(console_handler)
    return log


logger = _setup_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  SYSTEMD WATCHDOG – heartbeat żeby systemd wiedział że program żyje
# ─────────────────────────────────────────────────────────────────────────────
def watchdog_ping() -> None:
    """Wysyła sygnał WATCHDOG=1 do systemd przez gniazdo NOTIFY_SOCKET.
    Bez tego wywołania systemd uznaje program za zawieszony i go zabija.
    Bezpieczne do wywołania nawet gdy serwis nie jest uruchomiony przez systemd."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    try:
        # Gniazda zaczynające się od '@' używają przestrzeni nazw abstrakcyjnych
        addr = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"WATCHDOG=1", addr)
    except Exception:
        pass  # błąd watchdoga nie może zatrzymać programu

# ─────────────────────────────────────────────────────────────────────────────
#  STAN WSPÓŁDZIELONY (tylko wątek główny go modyfikuje – brak race condition)
# ─────────────────────────────────────────────────────────────────────────────
sensor            = None   # obiekt Adafruit_BMP280_I2C
sensor_error_cnt  = 0      # kolejne błędy odczytu I2C
push_error_cnt    = 0      # kolejne błędy git push
measurement_cnt   = 0      # łączna liczba wykonanych pomiarów


# ─────────────────────────────────────────────────────────────────────────────
#  INICJALIZACJA CZUJNIKA BMP280
# ─────────────────────────────────────────────────────────────────────────────
def init_sensor() -> bool:
    """Inicjalizuje magistralę I2C i czujnik BMP280.
    Zwraca True przy sukcesie, False przy błędzie."""
    global sensor, sensor_error_cnt
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        sensor = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=BMP280_ADDRESS)
        sensor_error_cnt = 0
        logger.info(f"Czujnik BMP280 zainicjowany pod adresem {hex(BMP280_ADDRESS)}.")
        return True
    except Exception as e:
        logger.error(f"Błąd inicjalizacji czujnika BMP280: {e}")
        sensor = None
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  ODCZYT TEMPERATURY – BMP280
# ─────────────────────────────────────────────────────────────────────────────
def get_bmp_temp() -> float | None:
    """Odczytuje temperaturę z BMP280 z korekcją.
    Po MAX_SENSOR_ERRORS kolejnych błędach próbuje reinicjalizować czujnik.
    Zwraca float lub None przy błędzie."""
    global sensor, sensor_error_cnt
    if sensor is None:
        return None
    try:
        value = round(sensor.temperature + TEMP_CORRECTION, 2)
        sensor_error_cnt = 0
        return value
    except Exception as e:
        sensor_error_cnt += 1
        logger.warning(
            f"Błąd odczytu BMP280 ({sensor_error_cnt}/{MAX_SENSOR_ERRORS}): {e}"
        )
        if sensor_error_cnt >= MAX_SENSOR_ERRORS:
            logger.error("Limit błędów czujnika przekroczony – próba reinicjalizacji I2C...")
            if init_sensor():
                logger.info("Czujnik ponownie zainicjowany pomyślnie.")
            else:
                logger.critical("Reinicjalizacja czujnika NIEUDANA.")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  ODCZYT TEMPERATURY – CPU (bez tworzenia obiektu przy każdym odczycie)
# ─────────────────────────────────────────────────────────────────────────────
def get_cpu_temp() -> float | None:
    """Odczytuje temperaturę CPU bezpośrednio z sysfs."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except OSError as e:
        logger.warning(f"Błąd odczytu temperatury CPU: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  ŚCIEŻKA PLIKU CSV – rotacja miesięczna
# ─────────────────────────────────────────────────────────────────────────────
def get_csv_path() -> str:
    """Zwraca ścieżkę do pliku CSV dla bieżącego miesiąca."""
    month = datetime.datetime.now().strftime("%Y-%m")
    return os.path.join(BASE_DIR, f"{CSV_PREFIX}_{month}.csv")


# ─────────────────────────────────────────────────────────────────────────────
#  SPRAWDZENIE WOLNEGO MIEJSCA NA DYSKU
# ─────────────────────────────────────────────────────────────────────────────
def check_disk_space() -> bool:
    """Sprawdza wolne miejsce na dysku.
    Zwraca False gdy jest krytycznie mało (zapis powinien być wstrzymany)."""
    try:
        free_mb = shutil.disk_usage(BASE_DIR).free / (1024 * 1024)
        if free_mb < MIN_DISK_MB:
            logger.critical(
                f"KRYTYCZNIE mało miejsca: {free_mb:.0f} MB! Wstrzymuję zapis danych."
            )
            return False
        if free_mb < WARN_DISK_MB:
            logger.warning(f"Mało miejsca na dysku: {free_mb:.0f} MB.")
        return True
    except OSError as e:
        logger.error(f"Błąd sprawdzania miejsca na dysku: {e}")
        return True  # nie blokuj pomiaru jeśli samo sprawdzenie zawiodło


# ─────────────────────────────────────────────────────────────────────────────
#  ZAPIS DO CSV (z blokadą pliku i wymuszonym zapisem na dysk)
# ─────────────────────────────────────────────────────────────────────────────
def _append_row(path: str, row: list, write_header: bool) -> None:
    """Pomocnicza: dopisuje jeden wiersz do pliku CSV z blokadą i fsync."""
    with open(path, mode="a", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["timestamp", "temp_bmp_c", "temp_cpu_c"])
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_to_csv() -> bool:
    """Zapisuje jeden pomiar do:
      - miesięcznego pliku CSV (dane_YYYY-MM.csv)  – rotacja, nie rośnie wiecznie
      - stałego pliku dane.csv                     – dla kompatybilności wstecznej
    Zwraca True przy sukcesie."""
    if not check_disk_space():
        return False

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bmp_temp  = get_bmp_temp()
    cpu_temp  = get_cpu_temp()

    if bmp_temp is None:
        logger.warning(f"{timestamp} – Brak odczytu BMP280, pomijam zapis do CSV.")
        return False

    row = [timestamp, bmp_temp, cpu_temp if cpu_temp is not None else ""]
    ok  = True

    # ── 1. Miesięczny plik (rotacja) ─────────────────────────────────────────
    monthly_path   = get_csv_path()
    monthly_header = not os.path.exists(monthly_path)
    try:
        _append_row(monthly_path, row, monthly_header)
    except OSError as e:
        logger.error(f"Błąd zapisu do pliku miesięcznego ({monthly_path}): {e}")
        ok = False

    # ── 2. Stały plik dane.csv (zbiorczy) ────────────────────────────────────
    fixed_header = not os.path.exists(FIXED_CSV_PATH)
    try:
        _append_row(FIXED_CSV_PATH, row, fixed_header)
    except OSError as e:
        logger.error(f"Błąd zapisu do dane.csv: {e}")
        # nie zwracaj False – miesięczny zapis mógł się udać

    if ok:
        logger.info(
            f"Pomiar #{measurement_cnt:>6} | {timestamp}"
            f" | BMP={bmp_temp}°C | CPU={cpu_temp}°C"
        )
    return ok


# ─────────────────────────────────────────────────────────────────────────────
#  GIT – push w osobnym wątku z timeoutem
# ─────────────────────────────────────────────────────────────────────────────
def _do_push(origin, result_box: list, error_box: list) -> None:
    try:
        result_box[0] = origin.push()
    except Exception as e:
        error_box[0] = e


def push_with_timeout(origin) -> None:
    """Wykonuje git push z limitem czasu PUSH_TIMEOUT_SEC.
    Rzuca TimeoutError lub wyjątek z git przy błędzie."""
    result_box = [None]
    error_box  = [None]
    t = threading.Thread(
        target=_do_push, args=(origin, result_box, error_box), daemon=True
    )
    t.start()
    t.join(timeout=PUSH_TIMEOUT_SEC)

    if t.is_alive():
        raise TimeoutError(
            f"git push przekroczył {PUSH_TIMEOUT_SEC}s – sieć niedostępna?"
        )
    if error_box[0]:
        raise error_box[0]


# ─────────────────────────────────────────────────────────────────────────────
#  GIT – rozmiar katalogu .git
# ─────────────────────────────────────────────────────────────────────────────
def _repo_size_mb(repo: git.Repo) -> float:
    try:
        total = sum(
            os.path.getsize(os.path.join(dirpath, fname))
            for dirpath, _, files in os.walk(repo.git_dir)
            for fname in files
        )
        return total / (1024 * 1024)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  GIT – commit i push
# ─────────────────────────────────────────────────────────────────────────────
def commit_and_push() -> None:
    """Dodaje wszystkie pliki CSV do commita i pcha zmiany na GitHub.
    Obsługuje: timeout sieci, non-fast-forward, błędy uwierzytelnienia."""
    global push_error_cnt

    if push_error_cnt >= MAX_PUSH_ERRORS:
        logger.error(
            f"Synchronizacja Git wstrzymana po {push_error_cnt} błędach z rzędu."
            " Sprawdź sieć i token GITHUB_TOKEN."
        )
        return

    try:
        repo = git.Repo(BASE_DIR)

        # Zbierz wszystkie miesięczne pliki CSV
        csv_files = [
            os.path.join(BASE_DIR, f)
            for f in os.listdir(BASE_DIR)
            if f.startswith(CSV_PREFIX) and f.endswith(".csv")
        ]

        if not csv_files:
            logger.info("Git: nie znaleziono plików CSV do commitowania.")
            return

        repo.index.add(csv_files)

        if not repo.is_dirty(index=True):
            logger.info("Git: brak nowych zmian w plikach CSV.")
            return

        label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        repo.index.commit(f"dane {label}")
        logger.info(f"Git commit: 'dane {label}'")

        origin = repo.remote(name="origin")
        push_with_timeout(origin)
        push_error_cnt = 0
        logger.info("Git push zakończony sukcesem.")

        # Lekki gc po każdym pushu – git sam zdecyduje, czy jest potrzebny
        try:
            repo.git.gc("--auto", "--quiet")
        except Exception:
            pass  # gc to operacja opcjonalna, nie przerywaj z jej powodu

        # Co 7 dni – pełny gc zapobiegający rozrostowi .git
        if measurement_cnt % GC_EVERY_N == 0:
            logger.info("Git: cotygodniowy gc --prune=all ...")
            try:
                repo.git.gc("--prune=all", "--quiet")
                size_mb = _repo_size_mb(repo)
                logger.info(f"Git: rozmiar .git po gc: {size_mb:.1f} MB")
                if size_mb > 500:
                    logger.warning(
                        f"Repozytorium Git zajmuje już {size_mb:.0f} MB!"
                        " Rozważ squash historii lub zmianę strategii synchronizacji."
                    )
            except Exception as gc_e:
                logger.warning(f"Git gc nieudany (niekrytyczny): {gc_e}")

    except TimeoutError as e:
        push_error_cnt += 1
        logger.error(f"Git push timeout [{push_error_cnt}/{MAX_PUSH_ERRORS}]: {e}")

    except git.exc.GitCommandError as e:
        push_error_cnt += 1
        msg = str(e).lower()
        if "non-fast-forward" in msg or "rejected" in msg:
            logger.warning(
                f"Git: non-fast-forward [{push_error_cnt}/{MAX_PUSH_ERRORS}]"
                " – próba git pull --rebase..."
            )
            try:
                repo = git.Repo(BASE_DIR)
                repo.git.pull("--rebase", "--quiet")
                push_error_cnt = max(0, push_error_cnt - 1)
                logger.info("Git pull --rebase zakończony sukcesem.")
            except Exception as pull_e:
                logger.error(f"git pull --rebase nieudany: {pull_e}")
        elif any(k in msg for k in ("authentication", "403", "401", "credentials")):
            logger.critical(
                f"Git: BŁĄD UWIERZYTELNIENIA [{push_error_cnt}/{MAX_PUSH_ERRORS}]!"
                " Sprawdź zmienną GITHUB_TOKEN."
            )
        else:
            logger.error(
                f"Git polecenie Git [{push_error_cnt}/{MAX_PUSH_ERRORS}]: {e}"
            )

    except Exception as e:
        push_error_cnt += 1
        logger.error(
            f"Nieoczekiwany błąd Git [{push_error_cnt}/{MAX_PUSH_ERRORS}]: {e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  PĘTLA GŁÓWNA
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    global measurement_cnt, push_error_cnt

    logger.info("=" * 64)
    logger.info("  Stacja Pogodowa BMP280 – START")
    logger.info(f"  Katalog:  {BASE_DIR}")
    logger.info(f"  Pomiar:   co {MEASUREMENT_SEC}s ({MEASUREMENT_SEC // 60} min)")
    logger.info(f"  Commit:   co {COMMIT_EVERY_N} pomiary"
                f" ({COMMIT_EVERY_N * MEASUREMENT_SEC // 60} min)")
    logger.info(f"  Git gc:   co {GC_EVERY_N} pomiarów (~7 dni)")
    logger.info(f"  Token:    {'USTAWIONY' if GITHUB_TOKEN else 'BRAK – push może się nie udać!'}")
    logger.info("=" * 64)

    if not GITHUB_TOKEN:
        logger.warning(
            "Brak zmiennej środowiskowej GITHUB_TOKEN."
            " Push do GitHub prawdopodobnie się nie powiedzie."
        )

    # Inicjalizacja czujnika – jeśli się nie uda, systemd zrestartuje program
    if not init_sensor():
        logger.critical(
            "Czujnik BMP280 niedostępny – kończę program."
            " (systemd wykona automatyczny restart za 30s)"
        )
        sys.exit(1)

    while True:
        loop_start = time.monotonic()

        try:
            measurement_cnt += 1

            # ── 0. Heartbeat watchdog – informuj systemd że program żyje ────
            watchdog_ping()

            # ── 1. Zapis pomiaru do CSV ──────────────────────────────────────
            saved = write_to_csv()

            # ── 2. Commit i push co COMMIT_EVERY_N pomiarów (co 15 min) ─────
            if saved and measurement_cnt % COMMIT_EVERY_N == 0:
                commit_and_push()

            # ── 3. Reset licznika błędów push raz na dobę (nowa szansa) ─────
            # 24h = 24 * (3600 / 300) = 288 pomiarów; commit co 3 → 96 commitów
            if measurement_cnt % 288 == 0:
                if push_error_cnt >= MAX_PUSH_ERRORS:
                    logger.info(
                        "Reset licznika błędów push – nowa próba synchronizacji po 24h."
                    )
                    push_error_cnt = 0

        except Exception as e:
            # Ostatnia siatka bezpieczeństwa – program NIE może zakończyć działania
            logger.exception(f"Nieoczekiwany błąd w pętli głównej: {e}")

        # ── Precyzyjne czekanie (uwzględnia czas wykonania operacji) ─────────
        elapsed    = time.monotonic() - loop_start
        sleep_time = max(0.0, MEASUREMENT_SEC - elapsed)
        next_time  = datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
        logger.info(f"Następny pomiar o {next_time.strftime('%H:%M:%S')}"
                    f" (za {sleep_time:.0f}s)")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()