"""Public HTTP/build support using independently generated local fixtures."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,build_opener,ProxyHandler
from urllib.parse import unquote,urlsplit
from urllib.error import HTTPError,URLError
from copy import deepcopy
import hashlib,hmac,json,os,secrets,select,shutil,subprocess,sys,tempfile,threading

class CandidateFailure(AssertionError):pass

class App:
    def __init__(self,project='/workspace'):
        self.project=Path(project);self.temp=tempfile.TemporaryDirectory(prefix='practice-check-');self.root=Path(self.temp.name);self.root.chmod(0o777)
        self.work=self.root/'work';self.process=None;self.provider=None;self.thread=None;self.log=None
        self.config=json.loads(Path(os.environ['PRACTICE_CONFIG']).read_text());self.config['provider_key']=secrets.token_hex(32)
        self.receipts={};self.provider_status={};self.provider_hits={};self.lock=threading.Lock()
        self.config_path=self.root/'config.json';self.db=self.root/'state.sqlite'
    def receipt(self,key,user='user-a',product='quarter',store='alpha',**extra):
        payload={'transaction_id':key,'user':user,'product':product,'store':store,'status':'paid',**extra}
        signature=hmac.new(bytes.fromhex(self.config['provider_key']),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
        self.receipts[key]={'payload':payload,'signature':signature}
        return {'transaction_id':key,'product':product,'store':store}
    def setup(self):
        if any(p.is_symlink() for p in self.project.rglob('*')):raise CandidateFailure('Source symlinks are not allowed')
        shutil.copytree(self.project,self.work,ignore=shutil.ignore_patterns('.git','dist','*.sqlite','*.sqlite-*','__pycache__','node_modules'))
        if os.getuid()==0:
            for p in [self.work,*self.work.rglob('*')]:os.chown(p,1000,1000)
        self.identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
        build=subprocess.run(['node','build.mjs'],cwd=self.work,capture_output=True,text=True,timeout=45,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp','UI_NODE_MODULES':os.environ['UI_NODE_MODULES']})
        if build.returncode:raise CandidateFailure('UI build failed: '+build.stderr[-2000:])
        owner=self
        class Provider(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                key=unquote(urlsplit(self.path).path.removeprefix('/receipts/'))
                with owner.lock:owner.provider_hits[key]=owner.provider_hits.get(key,0)+1
                status=owner.provider_status.get(key,200 if key in owner.receipts else 404)
                data=owner.receipts.get(key,{})
                body=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);self.thread=threading.Thread(target=self.provider.serve_forever,daemon=True);self.thread.start()
        self.config['provider']=f'http://127.0.0.1:{self.provider.server_port}'
        self.config_path.write_text(json.dumps(self.config));self.config_path.chmod(0o644)
        self.start();return self
    def start(self):
        self.log=open(self.root/'server.log','a+');env={'PATH':os.environ['PATH'],'HOME':'/tmp','PRACTICE_ASSETS':os.environ['PRACTICE_ASSETS'],'PRACTICE_CONFIG':str(self.config_path),'PRACTICE_DATABASE':str(self.db),'PORT':'0'}
        self.process=subprocess.Popen([sys.executable,'server.py'],cwd=self.work,env=env,stdout=subprocess.PIPE,stderr=self.log,text=True,**self.identity)
        if not select.select([self.process.stdout],[],[],10)[0]:raise CandidateFailure('Application failed to announce port')
        port=self.process.stdout.readline().strip()
        if not port.isdigit():self.log.seek(0);raise CandidateFailure('Application startup failed: '+self.log.read()[-2000:])
        self.url='http://127.0.0.1:'+port
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
        if self.provider:self.provider.shutdown();self.provider.server_close();self.thread.join(timeout=5)
        # Candidate-created private folders must be removed by their owner, not privileged reads.
        if self.work.exists():subprocess.run([sys.executable,'-c','import shutil,sys; shutil.rmtree(sys.argv[1])',str(self.work)],check=True,**getattr(self,'identity',{}), env={'PATH':os.environ['PATH'],'HOME':'/tmp','UI_NODE_MODULES':os.environ['UI_NODE_MODULES']})
        self.temp.cleanup()
    def request(self,path,data=None,token='',status=200,raw=False,headers=None,method=None):
        body=data if isinstance(data,bytes) else json.dumps(data).encode() if data is not None else None
        h={'Authorization':'Bearer '+token,'Content-Type':'application/json',**(headers or {})}
        try:response=build_opener(ProxyHandler({})).open(Request(self.url+path,data=body,headers=h,method=method),timeout=8)
        except HTTPError as error:response=error
        except (URLError,TimeoutError,ConnectionError) as error:raise CandidateFailure('Application request failed: '+str(error)) from error
        with response:
            body=response.read();actual=response.status;rh=dict(response.headers)
        if actual!=status:raise CandidateFailure(f'{path}: expected {status}, got {actual}: '+body[:200].decode(errors='replace'))
        if raw:return body,rh
        try:value=json.loads(body)
        except (ValueError,UnicodeError) as error:raise CandidateFailure('Invalid JSON response') from error
        if status>=400 and (not isinstance(value,dict) or not isinstance(value.get('error'),str)):raise CandidateFailure('Missing error string')
        return value
    def login(self,user='user-a'):
        value=self.request('/login',{'login':user,'password':'fixture-only'});assert isinstance(value,dict) and isinstance(value.get('token'),str) and value['token']
        return value['token']

def login_page(page,app,user='user-a'):
    page.goto(app.url);page.get_by_test_id('login').fill(user);page.get_by_test_id('password').fill('fixture-only');page.get_by_test_id('signin').click();page.get_by_test_id('tab-goals').wait_for()
