import csv

file_path = "dane.csv"

try:
    with open(file_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Column1", "Column2", "Column3"])
        writer.writerow(["Data1", "Data2", "Data3"])
    print("Plik zapisany pomyslnie!")
except IOError as e:
    print(f"Blad zapisu: {e}")
