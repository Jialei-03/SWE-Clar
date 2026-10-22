import os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
for command in [['dotnet','restore','TransactionsApi.csproj','--configfile','/opt/sweclar/NuGet.Config'],['dotnet','build','TransactionsApi.csproj','--no-restore','-p:UseSharedCompilation=false','-o','.build']]:
 subprocess.run(command,cwd=root,check=True)
