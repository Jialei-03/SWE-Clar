"""Protected observer: candidate code executes only in a separate ordinary process."""
import json,os,subprocess,sys
from pathlib import Path

def invoke(function,values):
 if os.geteuid()!=0:raise RuntimeError('Benchmark management identity required')
 root=Path(os.environ['CANDIDATE_ROOT'])
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(root),'function':function,'values':values}),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 if p.returncode:raise RuntimeError('Candidate invocation failed: '+p.stderr[-800:])
 result=json.loads(p.stdout)
 if 'error' in result:raise RuntimeError(result['error'])
 assert result['after']==values,'Candidate mutated caller-owned input'
 return result['result']
def transform(rows):return invoke('transform',rows)
def scrape(urls):return invoke('scrape',urls)
