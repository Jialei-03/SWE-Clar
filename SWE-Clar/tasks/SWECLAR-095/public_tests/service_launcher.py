"""Run the candidate builder/service with ordinary identity and explicit environment."""
import os,sys,json
from pathlib import Path
mode,work,config,database,assets,proof=sys.argv[1:]
env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
if mode=='build':
 for key in ['UI_NODE_MODULES','ESBUILD_BINARY_PATH']:env[key]=os.environ[key]
 command=['node','build.mjs']
else:
 env.update(STREAM_CONFIG=config,STREAM_DATABASE=database,STREAM_ASSETS=assets,PORT='0');command=[sys.executable,str(Path(work)/'server.py')]
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert os.getuid()==1000 and int(status['CapEff'],16)==0
Path(proof).write_text(json.dumps({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':0,'environment_keys':sorted(env),'mode':mode}))
os.chdir(work);os.execvpe(command[0],command,env)
