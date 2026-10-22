"""Benchmark preparation runs before the coding budget; no candidate imports."""
import base64,json,os,subprocess,sys,tempfile,time
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Benchmark management identity required')
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
private=Path(tempfile.mkdtemp(prefix='dotnet-management-'));private.chmod(0o700)
log=(private/'manager.log').open('w')
manager=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('service_manager.py')),str(private)],stdout=log,stderr=log,start_new_session=True)
try:
 ready=private/'ready.json'
 for _ in range(400):
  if ready.exists():break
  if manager.poll() is not None:raise RuntimeError('Database/certificate manager failed; protected log contains diagnostics')
  time.sleep(.1)
 else:raise RuntimeError('Database/certificate preparation timed out')
 config=json.loads(ready.read_text())
 config.update(API_PORT='8080',SERVER_PFX=str(root/'runtime/server.pfx'),CLIENT_CA_PEM=str(root/'runtime/ca.pem'))
 files={name:base64.b64encode((private/'certs'/name).read_bytes()).decode() for name in ['server.pfx','server.pem','ca.pem','client.pem','client.key']}
 script=r"""import base64,json,sys
from pathlib import Path
root=Path(sys.argv[1]);payload=json.load(sys.stdin);runtime=root/'runtime';runtime.mkdir(exist_ok=True)
for name,value in payload['files'].items():
 p=runtime/name;p.write_bytes(base64.b64decode(value));p.chmod(0o600)
p=runtime/'connection.json';p.write_text(json.dumps(payload['config']));p.chmod(0o600)
exclude=root/'.git/info/exclude'
if exclude.parent.is_dir():
 old=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in old.splitlines():exclude.write_text(old+'\n/runtime/\n')
"""
 subprocess.run([sys.executable,'-I','-c',script,str(root)],input=json.dumps({'files':files,'config':config}),text=True,user=1000,group=1000,extra_groups=[],check=True)
 print(json.dumps({'passed':True,'configuration':'runtime/connection.json','database':'fresh restricted database','tls':'fresh synthetic certificates','prepared_before_budget':True}))
except BaseException:
 manager.terminate();manager.wait(timeout=20);raise
finally:log.close()
