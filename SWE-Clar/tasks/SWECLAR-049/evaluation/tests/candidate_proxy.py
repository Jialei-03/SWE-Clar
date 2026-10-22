import json,os,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
def call(database,event):
 root=Path(os.environ['CANDIDATE_ROOT']);request={'project':str(root),'database':database,'event':event}
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],umask=0,env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 assert p.returncode==0,p.stderr[-800:]
 result=json.loads(p.stdout);assert 'error' not in result,result
 assert result['after']==event,'Caller event mutated'
 assert isinstance(result['result'],dict),'Function must return object'
 return result['result']
def load_solution():return SimpleNamespace(process_mentor_event=call,__file__=str(Path(os.environ['CANDIDATE_ROOT'])/'solution.py'))
