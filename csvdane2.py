import time
import datetime
import adafruit_bmp280
import board
import busio

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76)
# gpiozero for CPU
from gpiozero import CPUTemperature



# csv to be able to open file
import csv

# sets up the variables for the sensor
bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76)

# functions to use
while True:
	
	def cpu_temperature():
	    cpu = CPUTemperature()
	    cpu_temp = round(cpu.temperature, 2)
	    return str(cpu_temp)
	
	def get_temp():
	    temperature = sensor.temperature
	    temperature = round(temperature - 2, 2)  # Uwzgledniamy korekte -2 stopnie
	    return str(temperature)
	
	def date_now():
	    return datetime.datetime.now().strftime("%Y-%m-%d" + " %H:%M:%S")
	
	def write_to_csv():
	    try:
	        # Append mode ('a'), jesli plik nie istnieje, zostanie utworzony
	        with open("/home/foxune/pogoda/pogoda/dane.csv", mode="a", newline="") as sensor_readings:
	            sensor_write = csv.writer(sensor_readings, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
	            sensor_write.writerow([date_now(), get_temp(),])
	        print("Dane zapisane pomyslnie.")
	    except Exception as e:
	        print(f"Blad zapisu do pliku CSV: {e}")
	
	# Uruchomienie funkcji
	write_to_csv()

# Do some changes and commit 
	import git 
	repo = git.Repo('/home/foxune/pogoda/pogoda') 
	  
	file1 = 'dane.csv'
	repo.index.add([file1]) 
	print('Files Added Successfully') 
	repo.index.commit('Initial commit on new branch') 
	print('Commited successfully')
	origin = repo.remote(name='origin')
	origin.push()

	time.sleep(120)

