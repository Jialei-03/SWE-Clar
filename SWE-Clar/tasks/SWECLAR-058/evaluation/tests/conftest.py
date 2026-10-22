import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(os.environ['CANDIDATE_ROOT'])
def call(state,event):
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'state':state,'event':event}),capture_output=True,text=True,cwd=ROOT,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},timeout=15)
 assert p.returncode==0,p.stderr[-600:]
 result=json.loads(p.stdout);assert 'error' not in result,result
 assert json.dumps(result['after'],sort_keys=True)==json.dumps([state,event],sort_keys=True),'Inputs mutated'
 assert isinstance(result['result'],dict)
 return result['result']
