import git 
repo = git.Repo('/home/foxune/pogoda/pogoda') 
  
# Do some changes and commit 
file1 = "dane.csv"
repo.index.add([file1]) 
print('Files Added Successfully') 
repo.index.commit('Initial commit on new branch') 
print('Commited successfully')
origin = repo.remote(name='origin')
origin.push()
