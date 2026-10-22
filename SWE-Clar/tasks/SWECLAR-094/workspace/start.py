import os,sys,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
subprocess.run([sys.executable,str(root/'build.py')],check=True)
os.execvp('dotnet',['dotnet',str(root/'.build/TransactionsApi.dll'),'--urls','http://127.0.0.1:5080'])
