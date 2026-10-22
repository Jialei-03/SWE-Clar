"""Start the API with benchmark-generated development configuration."""
import json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
if os.geteuid()==0:
 os.setgroups([]);os.setgid(1000);os.setuid(1000)
config=json.loads((root/'runtime/connection.json').read_text())
subprocess.run([sys.executable,str(root/'build.py')],cwd=root,check=True)
env={**os.environ,**config,'DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1'}
if 'API_PORT' in os.environ:env['API_PORT']=os.environ['API_PORT']
os.chdir(root)
os.execvpe('dotnet',['dotnet',str(root/'.build/SetupApi.dll')],env)
