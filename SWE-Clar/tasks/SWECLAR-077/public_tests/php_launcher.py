"""Start PHP with a clean environment and no privileged submitted code."""
import os,sys,json,socket,shutil
from pathlib import Path
project,data,proof=sys.argv[1:];php=shutil.which('php')
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
env={'PATH':os.environ['PATH'],'HOME':'/tmp','DATA_ROOT':data}
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
Path(proof).write_text(json.dumps({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(env),'parent_sentinel_absent':not any('PRIVATE' in k for k in env)}));print(json.dumps({'port':port}),flush=True)
os.execve(php,[php,'-S','127.0.0.1:'+str(port),'-t',str(Path(project)/'web')],env)
