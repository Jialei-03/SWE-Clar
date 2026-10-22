import json,os,subprocess,sys,select
from pathlib import Path
from types import SimpleNamespace
worker=None

def reset():
 global worker
 if worker:
  worker.terminate()
  try:worker.wait(timeout=3)
  except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=3)
  worker=None

def request(value):
 global worker
 root=Path(os.environ['CANDIDATE_ROOT'])
 if worker is None:worker=subprocess.Popen([sys.executable,'-I','/public_tests/invoke.py'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 worker.stdin.write(json.dumps({'project':str(root),**value})+'\n');worker.stdin.flush()
 if not select.select([worker.stdout],[],[],15)[0]:raise subprocess.TimeoutExpired('candidate RPC',15)
 line=worker.stdout.readline();assert line,'Candidate worker closed';out=json.loads(line);assert 'error' not in out,out
 return out

def client(config):request({'configure':config});return True

def call(state,action,service=None):
 out=request({'state':state,'action':action,'service':service is not None});assert json.dumps(out['after'],sort_keys=True)==json.dumps([state,action],sort_keys=True),'Input mutation';assert isinstance(out['result'],dict)
 if 'error' in out['result']:assert isinstance(out['result']['error'].get('code'),str) and out['result']['error']['code']
 return out['result']
def load_solution():return SimpleNamespace(process_presave_action=call)
