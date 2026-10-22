"""Protected evaluator lifecycle. Only public candidate material runs as UID 1000."""
import base64,contextlib,hashlib,http.client,json,os,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPCookieProcessor,urlopen

IDENTITY={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
class CandidateFailure(AssertionError):pass

def candidate(cmd,**kwargs):
    try:r=subprocess.run(cmd,**IDENTITY,capture_output=True,text=True,timeout=kwargs.pop('timeout',20),**kwargs)
    except subprocess.TimeoutExpired as e:raise CandidateFailure('Candidate command exceeded its documented execution allowance') from e
    if r.returncode:raise CandidateFailure('Candidate command failed: '+r.stderr[-1000:]+r.stdout[-300:])
    return r.stdout

class App:
    def __init__(self):
        parent='/workspace' if Path('/workspace').is_dir() else '/tmp'
        self.root=Path(candidate([sys.executable,'-I','-c','import os,tempfile,sys;p=tempfile.mkdtemp(prefix="document-case-",dir=sys.argv[1]);os.chmod(p,0o777);print(p)',parent]).strip())
        source=Path(os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()));self.project=self.root/'project'
        def ignored(directory,names):
            skip={n for n in names if n in {'__pycache__','.pytest_cache'}}
            if Path(directory).resolve()==self.root.parent.resolve():skip.add(self.root.name)
            return skip
        shutil.copytree(source,self.project,symlinks=True,ignore=ignored)
        if os.geteuid()==0:
            for p in [self.project,*self.project.rglob('*')]:os.chown(p,1000,1000,follow_symlinks=False)
        self.data=self.root/'data';candidate([sys.executable,'-I','-c','import pathlib,sys;pathlib.Path(sys.argv[1]).mkdir()',str(self.data)])
        self.env={k:os.environ[k] for k in ['PATH','TCPDF_ROOT']};self.env.update(HOME=str(self.root),DOCUMENT_DATA_DIR=str(self.data));self.process=None;self.log=None
        candidate(['php','init.php','--reset'],cwd=self.project,env=self.env)

    def start(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}';self.log=open(self.root/'server.log','a+')
        self.process=subprocess.Popen(['php','-S',f'127.0.0.1:{port}','router.php'],cwd=self.project,env=self.env,stdout=self.log,stderr=self.log,**IDENTITY)
        for _ in range(100):
            if self.process.poll() is not None:raise CandidateFailure('Candidate PHP server exited')
            try:
                with urlopen(self.url,timeout=.2) as response:
                    if response.status==200:return self
            except OSError:time.sleep(.05)
        raise CandidateFailure('Candidate PHP HTTP server unavailable after successful environment preflight')

    def stop(self):
        if self.process:
            if self.process.poll() is None:self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
        if self.log:self.log.close();self.log=None

    def close(self):
        self.stop();candidate([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(self.root)])

    def script(self,code,*args):return candidate([sys.executable,'-I','-c',code,str(self.data),*args])

@contextlib.contextmanager
def application():
    app=App()
    try:yield app.start()
    finally:app.close()

class Client:
    def __init__(self,app,user=None):
        self.app=app;self.cookies=CookieJar();self.opener=build_opener(HTTPCookieProcessor(self.cookies))
        if user:self.call('/login','POST',{'username':user,'password':'demo-pass'})
    def call(self,path,method='GET',body=None,status=200,*,raw=False,headers=None,payload=None):
        headers=dict(headers or {})
        if payload is None and body is not None:payload=json.dumps(body,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        try:
            try:r=self.opener.open(Request(self.app.url+'/api'+path,method=method,data=payload,headers=headers),timeout=12)
            except HTTPError as e:r=e
            with r:
                data=r.read()
                if r.status!=status:raise CandidateFailure(f'{method} {path}: expected HTTP {status}, got {r.status}: '+data.decode(errors='replace')[:250])
                if raw:return data,dict(r.headers)
                try:return json.loads(data)
                except (UnicodeDecodeError,ValueError) as e:raise CandidateFailure('Candidate returned malformed JSON') from e
        except (OSError,http.client.HTTPException) as e:raise CandidateFailure('Candidate HTTP response failed: '+str(e)) from e

    def upload(self,data,filename='synthetic.png',status=201):
        boundary='sweclar-upload-boundary'
        payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n').encode()+data+f'\r\n--{boundary}--\r\n'.encode()
        return self.call('/assets','POST',status=status,payload=payload,headers={'Content-Type':'multipart/form-data; boundary='+boundary})


def persisted(app,data):
    # Search actual persisted content without imposing a reference table/column name.
    script='''import pathlib,sqlite3,sys,base64,json
root=pathlib.Path(sys.argv[1]);wanted=base64.b64decode(sys.stdin.read());found=False
for p in root.rglob('*'):
 if not p.is_file():continue
 raw=p.read_bytes()
 if raw==wanted:found=True
 if raw.startswith(b'SQLite format 3'):
  db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
  for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
   for row in db.execute('SELECT * FROM "'+table.replace('"','""')+'"'):
    if any(v==wanted or v==base64.b64encode(wanted).decode() for v in row):found=True
  db.close()
print(json.dumps(found))'''
    return json.loads(candidate([sys.executable,'-I','-c',script,str(app.data)],input=base64.b64encode(data).decode()))


def state_digest(app):
    # Logical DB records, not WAL bytes, timestamps or caller-provided manifests.
    script='''import pathlib,sqlite3,sys,json,hashlib,base64
out={}
for p in pathlib.Path(sys.argv[1]).rglob('*'):
 if not p.is_file():continue
 data=p.read_bytes();name=str(p.relative_to(sys.argv[1]))
 if data.startswith(b'SQLite format 3'):
  db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True);tables={}
  for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
   values=[]
   for r in db.execute('SELECT * FROM "'+t.replace('"','""')+'"'):
    values.append([{'blob_sha256':hashlib.sha256(v).hexdigest()} if isinstance(v,bytes) else v for v in r])
   tables[t]=sorted(values,key=lambda x:json.dumps(x,sort_keys=True))
  db.close();out[name]=tables
 elif not name.endswith(('-journal','-wal','-shm')):out[name]=hashlib.sha256(data).hexdigest()
print(hashlib.sha256(json.dumps(out,sort_keys=True).encode()).hexdigest())'''
    return app.script(script).strip()


def corrupt_stored_asset(app,data):
    script='''import pathlib,sqlite3,sys,base64,json
wanted=base64.b64decode(sys.argv[2]);changed=0
for p in pathlib.Path(sys.argv[1]).rglob('*'):
 if not p.is_file():continue
 raw=p.read_bytes()
 if raw==wanted:p.write_bytes(b'corrupt-png');changed+=1
 if raw.startswith(b'SQLite format 3'):
  db=sqlite3.connect(str(p))
  for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
   quoted='"'+table.replace('"','""')+'"';cols=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
   try:records=db.execute('SELECT rowid,* FROM '+quoted).fetchall()
   except sqlite3.OperationalError:continue
   for record in records:
    for col,value in zip(cols,record[1:]):
     if value==wanted or value==base64.b64encode(wanted).decode():
      replacement=b'corrupt-png' if isinstance(value,bytes) else base64.b64encode(b'corrupt-png').decode()
      db.execute('UPDATE '+quoted+' SET "'+col.replace('"','""')+'"=? WHERE rowid=?',(replacement,record[0]));changed+=1
  db.commit();db.close()
print(json.dumps(changed))'''
    assert json.loads(app.script(script,base64.b64encode(data).decode()))>0,'Uploaded content was not found in the documented persistent storage'
