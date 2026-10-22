import os,json,subprocess,sys
from types import SimpleNamespace

def run(helper,request):
 root=os.environ['CANDIDATE_ROOT'];env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
 for name in ['PLAYWRIGHT_BROWSERS_PATH']:
  if name in os.environ:env[name]=os.environ[name]
 p=subprocess.run([sys.executable,'-I','/public_tests/'+helper],input=json.dumps({'project':root,**request}),capture_output=True,text=True,cwd=root,user=1000,group=1000,extra_groups=[],env=env,timeout=120)
 assert p.returncode==0,p.stderr[-1200:];value=json.loads(p.stdout);assert 'error' not in value,value
 return value

def call(state,action,**options):
 result=run('invoke.py',{'state':state,'action':action,**options});assert json.dumps(result['after'],sort_keys=True)==json.dumps([state,action],sort_keys=True),'Inputs mutated';out=result['result'];assert isinstance(out,dict)
 if 'error' in out:assert isinstance(out['error'].get('code'),str) and out['error']['code']
 return out

def cli(state,operations,**options):return run('cli_worker.py',{'state':state,'operations':operations,**options})
