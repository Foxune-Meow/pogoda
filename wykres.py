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
plt.savefig('mytable.png')
