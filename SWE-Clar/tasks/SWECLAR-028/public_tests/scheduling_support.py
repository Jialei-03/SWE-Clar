"""Disposable local service and benchmark-owned receipt store."""
import json,os,shutil,signal,socket,sqlite3,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
from notification_fixture import NotificationFixture

def identity():return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}

class Application:
 def __init__(self,source=None,shifts=None,timezone='UTC'):
  self.root=Path(tempfile.mkdtemp(prefix='schedule-session-'));self.root.chmod(0o755)
  self.project=self.root/'work';self.private=self.root/'receipts';self.private.mkdir(mode=0o700)
  source=Path(source or os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()))
  if any(p.is_symlink() for p in source.rglob('*')):raise ValueError('Symlinks not allowed')
  shutil.copytree(source,self.project,ignore=shutil.ignore_patterns('runtime','.git','__pycache__','*.pyc'))
  runtime=self.project/'runtime';runtime.mkdir();self.database=runtime/'schedule.sqlite'
  # Public seed schema is created independently; never import candidate modules as the manager.
  with sqlite3.connect(self.database) as db:
   db.execute("CREATE TABLE shifts(id TEXT PRIMARY KEY,starts_at TEXT NOT NULL,location TEXT NOT NULL,address TEXT NOT NULL,map_url TEXT NOT NULL,manager_email TEXT NOT NULL,capacity INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'Open')")
   for row in shifts or []:db.execute('INSERT INTO shifts(id,starts_at,location,address,map_url,manager_email,capacity) VALUES(?,?,?,?,?,?,?)',tuple(row[k] for k in ['id','starts_at','location','address','map_url','manager_email','capacity']))
  self.fixture=NotificationFixture(self.private/'receipts.sqlite').start()
  (runtime/'config.json').write_text(json.dumps({'database':str(self.database),'notification_url':self.fixture.url,'timezone':timezone}))
  if os.geteuid()==0:
   for p in [self.project,*self.project.rglob('*')]:os.chown(p,1000,1000)
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
  self.url=f'http://127.0.0.1:{self.port}';self.process=None
 def start(self):
  self.process=subprocess.Popen([sys.executable,'server.py','--config','runtime/config.json','--port',str(self.port)],cwd=self.project,env={'PATH':os.environ['PATH'],'HOME':str(self.project/'runtime'),'PYTHONDONTWRITEBYTECODE':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,**identity())
  for _ in range(150):
   if self.process.poll() is not None:raise RuntimeError('Candidate server exited')
   try:
    if self.request('/health')=={'ready':True}:return self
   except OSError:pass
   time.sleep(.03)
  raise RuntimeError('Candidate startup timeout')
 def request(self,path,data=None):
  req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10) as r:return json.load(r)
 def close(self):
  if self.process:
   try:os.killpg(self.process.pid,signal.SIGTERM);self.process.wait(timeout=5)
   except ProcessLookupError:pass
   except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=5)
  self.fixture.close()
  subprocess.run([sys.executable,'-I','-c','import shutil,sys,pathlib;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]',str(self.project)],check=True,**identity())
  shutil.rmtree(self.root)
 def __enter__(self):
  try:return self.start()
  except BaseException:self.close();raise
 def __exit__(self,*_):self.close()
