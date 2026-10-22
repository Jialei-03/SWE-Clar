"""Evaluator-owned lifecycle helpers; the candidate executes with its normal UID."""
import contextlib
import http.client
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,'/opt/sweclar')
from watch_service import WatchService


class CandidateFailure(AssertionError):
    pass


IDENTITY={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}


class App:
    def __init__(self,fixture,provider):
        parent='/workspace' if Path('/workspace').exists() else '/tmp'
        create='import os,tempfile,sys; p=tempfile.mkdtemp(prefix="monitor-case-",dir=sys.argv[1]); os.chmod(p,0o777); print(p)'
        allocated=subprocess.run([sys.executable,'-I','-c',create,parent],**IDENTITY,capture_output=True,text=True,timeout=10)
        if allocated.returncode:raise RuntimeError('Evaluation workspace allocation failed: '+allocated.stderr[-500:])
        self.root=Path(allocated.stdout.strip())
        self.project=self.root/'project'
        source=Path(os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()))
        def ignored(directory,names):
            skip={name for name in names if name in {'__pycache__','.pytest_cache'}}
            if Path(directory).resolve()==self.root.parent.resolve():skip.add(self.root.name)
            return skip
        shutil.copytree(source,self.project,symlinks=True,ignore=ignored)
        if os.geteuid()==0:
            for p in [self.project,*self.project.rglob('*')]:os.chown(p,1000,1000,follow_symlinks=False)
        self.fixture=self.root/'fixture.json';self.fixture.write_text(json.dumps(fixture));self.fixture.chmod(0o644)
        self.db=self.root/'state.sqlite';self.provider=provider;self.process=None;self.log=None

    def start(self):
        self.log=open(self.root/'server.log','a+')
        self.process=subprocess.Popen([sys.executable,'server.py','--port','0','--db',str(self.db),'--fixtures',str(self.fixture),'--provider-url',self.provider.url],cwd=self.project,stdout=subprocess.PIPE,stderr=self.log,text=True,env={'PATH':os.environ['PATH'],'HOME':str(self.root),'PYTHONDONTWRITEBYTECODE':'1'},**IDENTITY)
        if not select.select([self.process.stdout],[],[],10)[0]:raise CandidateFailure('Candidate did not announce its port after prepared environment preflight')
        try:self.url='http://127.0.0.1:'+str(int(json.loads(self.process.stdout.readline())['port']))
        except (ValueError,KeyError,TypeError) as error:
            self.log.flush();self.log.seek(0)
            raise CandidateFailure('Candidate startup failed: '+self.log.read()[-1500:]) from error
        return self

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process.stdout.close();self.process=None
        if self.log:self.log.close();self.log=None

    def close(self):
        self.stop()
        script='import shutil,sys;shutil.rmtree(sys.argv[1])'
        result=subprocess.run([sys.executable,'-I','-c',script,str(self.root)],**IDENTITY,capture_output=True,text=True,timeout=10)
        if result.returncode:raise RuntimeError('Attempt cleanup failed: '+result.stderr[-500:])


@contextlib.contextmanager
def application(fixture,resources=None):
    with WatchService(resources or {'pages':{'page-one':'<p>Initial page</p>','page-two':'<p>Other page</p>'},'receipts':[]}) as provider:
        app=App(fixture,provider)
        try:
            app.start();yield app
        finally:app.close()


def request(app,path,token=None,body=None,status=200,raw=False,raw_body=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    payload=raw_body if raw_body is not None else json.dumps(body).encode() if body is not None else None
    if payload is not None:headers['Content-Type']='application/json'
    try:
        try:response=urlopen(Request(app.url+path,data=payload,headers=headers),timeout=9)
        except HTTPError as error:response=error
        with response:
            content=response.read()
            if response.status!=status:raise CandidateFailure(f'{path}: HTTP {response.status}, expected {status}: '+content.decode(errors='replace')[:300])
            if raw:return content,dict(response.headers)
            return json.loads(content)
    except (OSError,TimeoutError,http.client.HTTPException,ValueError) as error:
        raise CandidateFailure('Candidate response was unavailable or malformed: '+str(error)) from error


TABLES={
 'competitors':['account_id','competitor_id','name','archived'],
 'urls':['account_id','url_id','competitor_id','ordinal','url','text','sha256','observed_at_ms'],
 'snapshots':['account_id','snapshot_id','url_id','observed_at_ms','text','sha256'],
 'events':['account_id','snapshot_id','url_id','observed_at_ms','before_text','after_text','before_sha256','after_sha256'],
 'subscriptions':['account_id','sequence','plan','status'],
 'receipts':['account_id','id','sequence','plan','status'],
}


def rows(app,table):
    columns=TABLES[table]
    sql='SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+','.join(columns)
    script='import json,sqlite3,sys; db=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); db.row_factory=sqlite3.Row; print(json.dumps([dict(r) for r in db.execute(sys.argv[2])]))'
    result=subprocess.run([sys.executable,'-I','-c',script,str(app.db),sql],**IDENTITY,capture_output=True,text=True,timeout=10)
    if result.returncode:raise CandidateFailure('Documented database state could not be read: '+result.stderr[-500:])
    try:return json.loads(result.stdout)
    except ValueError as error:raise CandidateFailure('Invalid database read') from error


def business(app):
    return {name:rows(app,name) for name in TABLES}
