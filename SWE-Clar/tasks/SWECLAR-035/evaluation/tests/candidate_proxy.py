"""Protected parent observes a separate unprivileged candidate process."""
import json,os,subprocess,sys
from pathlib import Path

def call(state,action):
 if os.geteuid()!=0:raise RuntimeError('Benchmark management identity required')
 root=Path(os.environ['CANDIDATE_ROOT'])
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(root),'state':state,'action':action}),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 if p.returncode:raise RuntimeError('Candidate invocation failed: '+p.stderr[-800:])
 value=json.loads(p.stdout)
 if 'error' in value:raise RuntimeError(value['error'])
 assert value['after']==[state,action],'Caller inputs mutated'
 assert isinstance(value['result'],dict),'Result must be a JSON object'
 return value['result']


def cli(value):
 root=Path(os.environ['CANDIDATE_ROOT'])
 p=subprocess.run([sys.executable,str(root/'solution.py')],input=json.dumps(value),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 assert p.returncode==0,p.stderr[-800:]
 return json.loads(p.stdout)
