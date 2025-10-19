import time
import datetime
import adafruit_mcp9808 # Dodano MCP9808
import board
import busio
from gpiozero import CPUTemperature
import csv
import git

# Stałe konfiguracyjne
MCP9808_I2C_ADDRESS = 0x18  # Domyślny adres MCP9808, zmień jeśli inny

# Inicjalizacja magistrali I2C i czujnika MCP9808
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = adafruit_mcp9808.MCP9808(i2c, address=MCP9808_I2C_ADDRESS)
    print(f"Pomyślnie zainicjowano czujnik MCP9808 pod adresem {hex(MCP9808_I2C_ADDRESS)}.")
except ValueError as e:
    print(f"Błąd inicjalizacji czujnika MCP9808: Nie znaleziono czujnika pod adresem {hex(MCP9808_I2C_ADDRESS)}. Sprawdź połączenia i adres. {e}")
    sensor = None
except Exception as e:
    print(f"Błąd inicjalizacji czujnika MCP9808: {e}")
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

def get_mcp_temp():
    """Zwraca temperaturę z czujnika MCP9808."""
    if sensor:
        try:
            # Właściwość do odczytu temperatury w MCP9808 to .temperature
            temperature = round(sensor.temperature, 2) # Usunięto TEMP_OFFSET
            return str(temperature)
        except Exception as e:
            print(f"Błąd odczytu temperatury MCP9808: {e}")
            return "N/A"
    return "N/A"

def date_now():
    """Zwraca aktualną datę i godzinę."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def write_to_csv():
    """Zapisuje dane do pliku CSV."""
    current_temp = get_mcp_temp()
    
    if current_temp == "N/A":
        print("Nie udało się odczytać temperatury z MCP9808, pomijam zapis do CSV.")
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
        print("Czujnik MCP9808 nie został poprawnie zainicjowany. Sprawdź logi. Program może nie działać poprawnie.")
        # Można tutaj zdecydować, czy program ma się zakończyć, czy próbować dalej bez czujnika.
        # exit(1) # Aby zakończyć, odkomentuj
    
    print("Rozpoczynam pętlę pomiarową...")
    while True:
        try:
            write_to_csv()
            commit_and_push()
        except Exception as e:
            print(f"Nieoczekiwany błąd w pętli głównej: {e}")

        print(f"Następny odczyt za 300 sekund (o {datetime.datetime.now() + datetime.timedelta(seconds=300)})")
        time.sleep(300)  # Oczekiwanie 5 minuty przed kolejną iteracją
