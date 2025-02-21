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
	
	
	import pandas as pd
	df = pd.read_csv('dane.csv',header=None)
	print(df.head())
	t = df[0]
	v = df[1]
	
	
	from matplotlib import pyplot as plt
	
	fig, ax = plt.subplots(figsize=(14,15))
	ax.plot(t,v,lw=4)
	plt.xticks(rotation=90)
	ax.set_xlabel('Data [hh:mm:ss]',fontsize=14)
	ax.set_ylabel('Temperatura [$C$]',fontsize=14)
	ax.set_title('Wykres temperatury',fontsize=14)
	plt.savefig('tabela.png')
	
	
	import git 
	repo = git.Repo('/home/foxune/pogoda/pogoda') 
	  

# Do some changes and commit 
	file1 = 'dane.csv'
	file2 = 'tabela.png'
	repo.index.add([file1, file2]) 
	print('Files Added Successfully') 
	repo.index.commit('Initial commit on new branch') 
	print('Commited successfully')
	origin = repo.remote(name='origin')
	origin.push()

	time.sleep(120)

