import os,sys,subprocess,json
from pathlib import Path
class Proxy:
 def build_article_package(self,params,url,output_dir,fetch_text=None):
  target=Path(output_dir);assert target.is_relative_to('/tmp');target.mkdir(parents=True,exist_ok=True)
  if os.getuid()==0:
   # Parent pytest temp directories are private by default; expose only the fixture ancestry.
   for parent in [target,*target.parents]:
    if str(parent) in ['/','/tmp']:break
    parent.chmod(0o755)
   target.chmod(0o777)
  data={'params':params,'url':url,'output':str(target),'use_adapter':fetch_text is not None}
  if fetch_text:
   try:data['html']=fetch_text(url)
   except Exception:data['fetch_failure']=True
  r=subprocess.run([sys.executable,'-I','/public_tests/invoke.py',str(Path(os.environ['SWECLAR_PROJECT_DIR']))],input=json.dumps(data),capture_output=True,text=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_PRIVATE_WORKER_SENTINEL':'parent-private'},timeout=25)
  proof=json.loads(next(line[len('CLARSWE_PROCESS '):] for line in r.stderr.splitlines() if line.startswith('CLARSWE_PROCESS ')))
  assert proof['uid']==1000 and proof['cap_eff']==0 and not any('PRIVATE' in k for k in proof['environment_keys'])
  Path('/private/results').mkdir(parents=True,exist_ok=True)
  with open('/private/results/worker-isolation.jsonl','a') as out:out.write(json.dumps(proof)+'\n')
  assert r.returncode==0,r.stderr
  value=json.loads(r.stdout);assert value['params']==params,'input mutation'
  if data['use_adapter'] and ('error' not in value['result'] or value['result'].get('error',{}).get('code') in ['invalid_archive','fetch_failed']):assert value['seen']==[url]
  return value['result']
def load_solution():return Proxy()
