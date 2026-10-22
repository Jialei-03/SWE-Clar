"""Prepare the local database and synthetic configuration before coding starts."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Run task preparation through the benchmark manager')
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
private=Path(tempfile.mkdtemp(prefix='portal-management-'));private.chmod(0o700)
log=(private/'manager.log').open('w')
manager=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('service_manager.py')),str(private)],stdout=log,stderr=log,start_new_session=True)
try:
 ready=private/'ready.json'
 for _ in range(400):
  if ready.exists():break
  if manager.poll() is not None:raise RuntimeError('Database manager failed; see protected management log')
  time.sleep(.1)
 else:raise RuntimeError('Database preparation timed out')
 config=json.loads(ready.read_text());config['PORTAL_BOOTSTRAP']=str(root/'runtime/bootstrap.json')
 bootstrap={'centres':{'demo':{'name':'Example centre'}},'children':{'sample-child':{'centre_id':'demo'}},'users':{'sample-admin':{'role':'admin','centre_ids':['demo'],'child_ids':[],'pin':'2468'}}}
 script="""import json,sys,os
from pathlib import Path
root=Path(sys.argv[1]);payload=json.load(sys.stdin);runtime=root/'runtime';runtime.mkdir(exist_ok=True)
for name,data in payload.items():
 p=runtime/name;p.write_text(json.dumps(data));p.chmod(0o600)
exclude=root/'.git/info/exclude'
if exclude.parent.is_dir():
 old=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in old.splitlines():exclude.write_text(old+'\\n/runtime/\\n')
"""
 subprocess.run([sys.executable,'-I','-c',script,str(root)],input=json.dumps({'connection.json':config,'bootstrap.json':bootstrap}),text=True,user=1000,group=1000,extra_groups=[],check=True)
 print(json.dumps({'passed':True,'database':'portal_development','configuration':'runtime/connection.json','prepared_before_budget':True}))
except BaseException:
 manager.terminate();manager.wait(timeout=20);raise
finally:log.close()
