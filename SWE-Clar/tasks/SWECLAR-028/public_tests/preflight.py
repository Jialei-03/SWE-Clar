"""Prepare writable demo data and notification service before candidate work."""
import json,os,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from scheduling_support import identity

def main():
 runtime=Path('/workspace/runtime')
 private=Path('/tmp/scheduling-notifications');private.mkdir(mode=0o700,exist_ok=True)
 url='http://127.0.0.1:38920'
 def health():
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'/health',timeout=.5) as response:return json.load(response)=={'ready':True}
 try:ready=health()
 except OSError:ready=False
 if not ready:
  process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--serve'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  for _ in range(100):
   try:
    if health():break
   except OSError:pass
   if process.poll() is not None:raise RuntimeError('Notification service exited')
   time.sleep(.03)
  else:raise RuntimeError('Notification service unavailable')
 prepare='import json,sqlite3\nfrom pathlib import Path\nruntime=Path("/workspace/runtime");runtime.mkdir(exist_ok=True)\nurl='+repr(url)+'\n'+'dbpath=runtime/\'schedule.sqlite\'\nif not dbpath.exists():\n with sqlite3.connect(dbpath) as db:\n  db.execute("CREATE TABLE shifts(id TEXT PRIMARY KEY,starts_at TEXT NOT NULL,location TEXT NOT NULL,address TEXT NOT NULL,map_url TEXT NOT NULL,manager_email TEXT NOT NULL,capacity INTEGER NOT NULL,status TEXT NOT NULL DEFAULT \'Open\')")\n  db.execute(\'INSERT INTO shifts(id,starts_at,location,address,map_url,manager_email,capacity) VALUES(?,?,?,?,?,?,?)\',(\'shift-a\',\'2030-04-03T10:00:00+00:00\',\'Synthetic hall\',\'Fixture lane\',\'https://maps.example.test/a\',\'manager@example.test\',4))\nif not (runtime/\'config.json\').exists():(runtime/\'config.json\').write_text(json.dumps({\'database\':str(dbpath),\'notification_url\':url,\'timezone\':\'UTC\'}))'
 subprocess.run([sys.executable,'-I','-c',prepare],check=True,**identity())
 code="""from pathlib import Path
p=Path('/workspace/runtime/write-check');p.write_text('ok');p.unlink()
e=Path('/workspace/.git/info/exclude')
if e.parent.exists():
 s=e.read_text() if e.exists() else ''
 if '/runtime/' not in s.splitlines():e.write_text(s+'\\n/runtime/\\n')
"""
 subprocess.run([sys.executable,'-I','-c',code],check=True,**identity())
 print(json.dumps({'passed':True,'notification_service_ready':True,'runtime_writable':True,'synthetic_seed_ready':True}))
if __name__=='__main__':
 if '--serve' in sys.argv:
  from notification_fixture import NotificationFixture
  fixture=NotificationFixture('/tmp/scheduling-notifications/receipts.sqlite',port=38920)
  fixture.server.serve_forever()
 else:main()
