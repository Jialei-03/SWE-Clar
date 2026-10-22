import os,subprocess,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as home:
 env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':home,'CI':'true'}
 subprocess.run(['flutter','pub','get','--offline','--enforce-lockfile'],env=env,check=True)
 subprocess.run(['node','--check','server/server.cjs'],env=env,check=True)
print('Prepared offline Flutter project and Node source checked')
