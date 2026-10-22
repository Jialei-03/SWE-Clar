import os,sys,json
from pathlib import Path
root,url,state,proof=sys.argv[1:]
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
keys=['GRAPH_URL','HOME','PATH','PORT','PYTHONDONTWRITEBYTECODE','STATE_PATH']
Path(proof).write_text(json.dumps({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':keys,'parent_sentinel_absent':True}))
os.chdir(root);os.execve(sys.executable,[sys.executable,str(Path(root)/'server.py')],{'PATH':os.environ['PATH'],'HOME':'/tmp','PORT':'0','GRAPH_URL':url,'STATE_PATH':state,'PYTHONDONTWRITEBYTECODE':'1'})
