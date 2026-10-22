"""Build using the benchmark's prepared offline package cache."""
import os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
home=root/'.dotnet-home';home.mkdir(exist_ok=True)
env={**os.environ,'HOME':str(home),'DOTNET_CLI_HOME':str(home),'DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false'}
subprocess.run(['dotnet','restore',str(root/'SetupApi.csproj'),'--configfile','/opt/sweclar/NuGet.Config'],cwd=root,env=env,check=True)
subprocess.run(['dotnet','build',str(root/'SetupApi.csproj'),'--no-restore','-p:UseSharedCompilation=false','-o',str(root/'.build')],cwd=root,env=env,check=True)
