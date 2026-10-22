"""Execute a compiler or native application with the ordinary candidate identity."""
import os,sys,json
from pathlib import Path
cwd,proof,*command=sys.argv[1:]
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
Path(proof).write_text(json.dumps({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':['HOME','LANG','PATH']}))
os.chdir(cwd);os.execvpe(command[0],command,{'PATH':os.environ['PATH'],'HOME':'/tmp','LANG':'C.UTF-8'})
