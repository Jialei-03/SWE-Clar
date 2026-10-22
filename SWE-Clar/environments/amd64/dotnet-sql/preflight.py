"""Independent shared runtime health, before candidate budget."""
import json,os,subprocess,sys
from pathlib import Path
base=subprocess.run([sys.executable,'-I','/opt/sweclar/web_preflight.py'],capture_output=True,text=True,check=True)
assert json.loads(base.stdout)['passed']
sql=subprocess.run([sys.executable,'/opt/sweclar/check_database.py'],capture_output=True,text=True,check=True,timeout=50)
assert json.loads(sql.stdout)['passed']
code="""import os,shutil,subprocess,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='sdk-health-') as d:
 root=Path(d);shutil.copytree('/opt/sweclar/dotnet-probe',root/'src')
 env={**os.environ,'HOME':d,'DOTNET_CLI_HOME':d,'DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK':'1','DOTNET_NOLOGO':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false'}
 for args in [['dotnet','restore',str(root/'src/Probe.csproj'),'--configfile','/opt/sweclar/NuGet.Config'],['dotnet','build',str(root/'src/Probe.csproj'),'--no-restore','-p:UseSharedCompilation=false','-o',str(root/'bin')]]:
  subprocess.run(args,env=env,check=True,capture_output=True,text=True,timeout=30)
 result=subprocess.run(['dotnet',str(root/'bin/Probe.dll')],env=env,check=True,capture_output=True,text=True)
 assert result.stdout.strip()=='MySqlConnector.MySqlConnection'
"""
subprocess.run([sys.executable,'-I','-c',code],user=1000,group=1000,extra_groups=[],check=True,timeout=70)
print(json.dumps({'passed':True,'profile':'dotnet-sql','database':json.loads(sql.stdout),'dotnet_offline_uid1000_compile':True,'base_profile_passed':True}))
