import time
import datetime
import adafruit_bmp280
import board
import busio
from gpiozero import CPUTemperature
import csv
import git

# Stałe konfiguracyjne
BMP280_I2C_ADDRESS = 0x76  # Domyślny adres BMP280

# Inicjalizacja magistrali I2C i czujnika BMP280
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=BMP280_I2C_ADDRESS)
    print(f"Pomyślnie zainicjowano czujnik BMP280 pod adresem {hex(BMP280_I2C_ADDRESS)}.")
except ValueError as e:
    print(f"Błąd inicjalizacji czujnika BMP280: Nie znaleziono czujnika pod adresem {hex(BMP280_I2C_ADDRESS)}. Sprawdź połączenia i adres. {e}")
    sensor = None
except Exception as e:
    print(f"Błąd inicjalizacji czujnika BMP280: {e}")
    sensor = None  # Zapobieganie błędom w dalszej części kodu

# Ścieżka do pliku CSV
csv_file_path = "/home/foxune/pogoda/pogoda/dane.csv"

def cpu_temperature():
    """Zwraca temperaturę CPU."""
    try:
        cpu = CPUTemperature()
        return str(round(cpu.temperature, 2))
    except Exception as e:
        print(f"Błąd odczytu temperatury CPU: {e}")
        return "N/A"

def get_bmp_temp():
    """Zwraca temperaturę z czujnika BMP280."""
    if sensor:
        try:
            temperature = round(sensor.temperature - 2, 2)  # Korekta -2°C
            return str(temperature)
        except Exception as e:
            print(f"Błąd odczytu temperatury BMP280: {e}")
            return "N/A"
    return "N/A"

def date_now():
    """Zwraca aktualną datę i godzinę."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def write_to_csv():
    """Zapisuje dane do pliku CSV."""
    current_temp = get_bmp_temp()
    
    if current_temp == "N/A":
        print("Nie udało się odczytać temperatury z BMP280, pomijam zapis do CSV.")
        return

    try:
        with open(csv_file_path, mode="a", newline="") as sensor_readings:
            sensor_write = csv.writer(sensor_readings, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            sensor_write.writerow([date_now(), current_temp])
        print(f"Dane zapisane pomyślnie: {date_now()}, {current_temp}°C")
    except Exception as e:
        print(f"Błąd zapisu do pliku CSV: {e}")

def commit_and_push():
    """Dodaje zmiany do GIT-a i wysyła na zdalne repozytorium."""
    try:
        repo = git.Repo('/home/foxune/pogoda/pogoda')
        if repo.is_dirty(path=csv_file_path):
            repo.index.add([csv_file_path])
            print('Plik dodany do commit.')
            repo.index.commit(f'Aktualizacja danych pogodowych - {date_now()}')
            print('Commit wykonany.')
            origin = repo.remote(name='origin')
            origin.push()
            print('Zmiany wysłane do repozytorium.')
        else:
            print('Brak zmian w pliku CSV do commitowania.')
    except git.exc.GitCommandError as e:
        print(f"Błąd polecenia GIT: {e}")
        if "nothing to commit" in str(e).lower():
            print("Brak zmian do commitowania (wykryto przez GitCommandError).")
        elif "non-fast-forward" in str(e).lower():
            print("Problem z wypchnięciem zmian. Może być konieczne wykonanie 'git pull' ręcznie.")
    except Exception as e:
        print(f"Błąd podczas operacji GIT: {e}")

# Pętla główna
if __name__ == "__main__":
    if sensor is None:
        print("Czujnik BMP280 nie został poprawnie zainicjowany. Sprawdź logi.")
    
    print("Rozpoczynam pętlę pomiarową...")
    while True:
        try:
            write_to_csv()
            commit_and_push()
        except Exception as e:
            print(f"Nieoczekiwany błąd w pętli głównej: {e}")

        print(f"Następny odczyt za 300 sekund (o {datetime.datetime.now() + datetime.timedelta(seconds=300)})")
        time.sleep(300)
