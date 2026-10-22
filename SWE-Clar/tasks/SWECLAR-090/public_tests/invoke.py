"""Public execution boundary and optional text adapter, without business assertions."""
import os,sys,json
from pathlib import Path
if '--worker' not in sys.argv:
 project=sys.argv[1]
 if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
 os.execve(sys.executable,[sys.executable,'-I',__file__,'--worker',project],{'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
data=json.loads(sys.stdin.read());seen=[]
def fetch(url):
 seen.append(url)
 if data.get('fetch_failure'):raise OSError('Synthetic failure')
 return data['html']
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
proof={'uid':os.getuid(),'pid':os.getpid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(os.environ)}
print('CLARSWE_PROCESS '+json.dumps(proof),file=sys.stderr,flush=True)
sys.path.insert(0,sys.argv[2]);from solution import build_article_package
result=build_article_package(data['params'],data['url'],data['output'],fetch_text=fetch if data.get('use_adapter') else None)
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
print(json.dumps({'result':result,'params':data['params'],'seen':seen,'proof':{'uid':os.getuid(),'pid':os.getpid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(os.environ)}}))
