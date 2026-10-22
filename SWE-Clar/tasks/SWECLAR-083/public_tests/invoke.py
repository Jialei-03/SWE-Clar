"""Run the public function contract at the same privilege as the candidate."""
import os,sys,json
from pathlib import Path
if '--worker' not in sys.argv:
 root=sys.argv[1]
 if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
 os.execve(sys.executable,[sys.executable,'-I',__file__,'--worker',root],{'PATH':os.environ['PATH'],'HOME':'/tmp'})
sys.path.insert(0,sys.argv[2]);from solution import process_navigation_action
from router import GraphClient
state,action,url=json.loads(sys.stdin.read());result=process_navigation_action(state,action,GraphClient(url))
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
print(json.dumps({'result':result,'state':state,'action':action,'proof':{'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(os.environ)}}))
