"""Public process/HTTP helper for the prepared local application."""
import json,os,select,shutil,subprocess,sys,tempfile
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,ProxyHandler


class CandidateFailure(AssertionError):pass


class App:
    def __init__(self,project='/workspace',fixtures=None):
        self.project=Path(project);self.fixtures=fixtures;self.process=None;self.log=None
        self.temp=tempfile.TemporaryDirectory(prefix='network-check-');self.root=Path(self.temp.name);self.root.chmod(0o777)
        self.work=self.root/'work';self.db=self.root/'network.sqlite';self.config=self.root/'fixtures.json'
        self.identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
    def setup(self):
        if any(p.is_symlink() for p in self.project.rglob('*')):raise CandidateFailure('Candidate source symlinks are not permitted')
        shutil.copytree(self.project,self.work,ignore=shutil.ignore_patterns('.git','*.sqlite','*.sqlite-*','__pycache__'))
        if os.getuid()==0:
            for path in [self.work,*self.work.rglob('*')]:os.chown(path,1000,1000)
        if self.fixtures is None:self.fixtures=json.loads((self.work/'fixtures/demo.json').read_text())
        self.config.write_text(json.dumps(self.fixtures));self.config.chmod(0o644)
        self.start();return self
    def start(self):
        self.log=open(self.root/'server.log','a+')
        self.process=subprocess.Popen([sys.executable,'app.py','--db',str(self.db),'--fixtures',str(self.config),'--port','0'],cwd=self.work,stdout=subprocess.PIPE,stderr=self.log,text=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        if not select.select([self.process.stdout],[],[],10)[0]:raise CandidateFailure('Application did not announce its port')
        port=self.process.stdout.readline().strip()
        if not port.isdigit():
            self.log.seek(0);raise CandidateFailure('Application startup failed: '+self.log.read()[-2000:])
        self.url='http://127.0.0.1:'+port
        assert self.request('/health')=={'ok':True}
    def stop(self):
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
            self.process.stdout.close();self.process=None
        if self.log:self.log.close();self.log=None
    def __enter__(self):
        try:return self.setup()
        except BaseException:self.__exit__(None,None,None);raise
    def __exit__(self,*_):
        self.stop()
        # Remove candidate-created private directories as their owner.
        if self.work.exists():subprocess.run([sys.executable,'-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(self.work)],check=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        self.temp.cleanup()
    def request(self,path,data=None,token='',status=200,method=None,raw=False):
        body=data if isinstance(data,bytes) else json.dumps(data).encode() if data is not None else None
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
        try:response=build_opener(ProxyHandler({})).open(Request(self.url+path,data=body,headers=headers,method=method),timeout=8)
        except HTTPError as e:response=e
        except (URLError,TimeoutError,ConnectionError) as e:raise CandidateFailure('Application request failed: '+str(e)) from e
        with response:payload=response.read();actual=response.status
        if actual!=status:raise CandidateFailure(f'{path}: expected {status}, got {actual}: '+payload[:300].decode(errors='replace'))
        if raw:return payload
        try:value=json.loads(payload)
        except (ValueError,UnicodeError) as e:raise CandidateFailure('Application response was not JSON') from e
        if status>=400:assert isinstance(value,dict) and isinstance(value.get('error'),dict) and isinstance(value['error'].get('code'),str)
        return value
    def login(self,user='u1'):
        account=next(u for u in self.fixtures['accounts'] if u['id']==user)
        result=self.request('/api/login',{'id':user,'password':account['password']})
        assert isinstance(result.get('token'),str) and result['token'];return result['token']
    def database_probe(self):
        result=subprocess.run([sys.executable,'-c',"import json,sqlite3,sys;db=sqlite3.connect(sys.argv[1]);print(json.dumps({'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'tables':len(db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall())}))",str(self.db)],capture_output=True,text=True,check=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        return json.loads(result.stdout)


def login_page(page,app,user='u1'):
    account=next(u for u in app.fixtures['accounts'] if u['id']==user)
    page.goto(app.url);page.locator('#username').fill(user);page.locator('#password').fill(account['password']);page.locator('#login button').click();page.locator('#workspace').wait_for(state='visible');page.locator('#identity').filter(has_text=user).wait_for()
