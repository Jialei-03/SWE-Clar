import os,json,subprocess,sys
from types import SimpleNamespace

def run(helper,request):
 root=os.environ['CANDIDATE_ROOT'];env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
 for name in ['PLAYWRIGHT_BROWSERS_PATH']:
  if name in os.environ:env[name]=os.environ[name]
 p=subprocess.run([sys.executable,'-I','/public_tests/'+helper],input=json.dumps({'project':root,**request}),capture_output=True,text=True,cwd=root,user=1000,group=1000,extra_groups=[],env=env,timeout=35)
 assert p.returncode==0,p.stderr[-1200:];value=json.loads(p.stdout);assert 'error' not in value,value
 return value

def call(request):
 result=run('invoke.py',{'request':request});assert result['after']==request,'Inputs mutated'
 if result.get('rejected'):return result
 assert isinstance(result.get('result'),dict);return result['result']

def cli(request,offset=0,limit=20):return run('cli_worker.py',{'request':request,'offset':offset,'limit':limit})
