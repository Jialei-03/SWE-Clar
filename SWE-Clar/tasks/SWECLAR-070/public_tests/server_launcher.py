"""Execute the submitted HTTP service with a clean unprivileged boundary."""
import os,sys,json
from pathlib import Path
project,config,database,proof=sys.argv[1:]
if os.getuid()==0:
 os.setgroups([]);os.setgid(1000);os.setuid(1000)
env={'PATH':os.environ['PATH'],'HOME':'/tmp','PORT':'0','ROOF_CONFIG':config,'ROOF_DATABASE':database,'PYTHONDONTWRITEBYTECODE':'1'}
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
Path(proof).write_text(json.dumps({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(env),'parent_sentinel_absent':not any('PRIVATE' in k for k in env)}))
os.chdir(project);os.execve(sys.executable,[sys.executable,str(Path(project)/'server.py')],env)
