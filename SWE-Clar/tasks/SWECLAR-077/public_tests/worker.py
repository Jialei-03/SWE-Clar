"""Public neutral JSON adapter; submitted Python executes unprivileged."""
import os,sys,json,socket
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
for key in list(os.environ):
 if key not in ['PATH','HOME']:del os.environ[key]
from pathlib import Path
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
print(json.dumps({'ready':True,'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(os.environ)}),flush=True)
attempts=[]
def denied(*args,**kwargs):
 attempts.append('socket connection');raise RuntimeError('No network access in local processor')
socket.socket.connect=denied;socket.create_connection=denied
sys.path.insert(0,sys.argv[1]);from solution import process_site_action
for line in sys.stdin:
 try:
  v=json.loads(line);state,action=v['state'],v['action'];result=process_site_action(state,action,v['output_root'],v['source_root']);print(json.dumps({'result':result,'state':state,'action':action,'network_attempts':list(attempts)}),flush=True)
 except Exception as e:print(json.dumps({'exception':type(e).__name__+': '+str(e)}),flush=True)
