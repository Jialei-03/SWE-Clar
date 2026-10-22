import os,sys,subprocess,tempfile,shutil,json
from pathlib import Path
ENV={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','DOTNET_ROOT':'/opt/dotnet','DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1','NUGET_PACKAGES':'/opt/sweclar/nuget-cache'}
if os.getuid()==0:
 r=subprocess.run([sys.executable,'-I',__file__],user=1000,group=1000,extra_groups=[],env=ENV);raise SystemExit(r.returncode)
assert os.getuid()==1000
with tempfile.TemporaryDirectory() as d:
 p=Path(d);shutil.copytree('/opt/sweclar/sqlite-probe',p/'src')
 for cmd in [['dotnet','restore',str(p/'src/Probe.csproj'),'--configfile','/opt/sweclar/NuGet.Config'],['dotnet','build',str(p/'src/Probe.csproj'),'--no-restore','-p:UseSharedCompilation=false','-o',str(p/'app')],['dotnet',str(p/'app/Probe.dll')]]:
  r=subprocess.run(cmd,cwd=p,env=ENV,capture_output=True,text=True);assert r.returncode==0,r.stdout+r.stderr
 assert (p/'probe.sqlite').read_bytes().startswith(b'SQLite format 3')
print(json.dumps({'passed':True,'profile':'dotnet-sqlite','uid':os.getuid(),'offline_dotnet_sqlite':True}))
