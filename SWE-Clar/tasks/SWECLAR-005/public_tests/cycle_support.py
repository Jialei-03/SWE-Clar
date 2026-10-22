"""Public isolated static server and full-Chromium support."""
from pathlib import Path
import os,select,shutil,subprocess,sys,tempfile

class CandidateFailure(AssertionError):pass

class Site:
    def __init__(self,project='/workspace'):
        self.project=Path(project);self.temp=tempfile.TemporaryDirectory(prefix='cycle-check-');self.root=Path(self.temp.name);self.root.chmod(0o777);self.work=self.root/'work';self.process=None;self.log=None
        self.identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
    def __enter__(self):
        try:
            if any(p.is_symlink() for p in self.project.rglob('*')):raise CandidateFailure('Candidate source symlinks are not allowed')
            shutil.copytree(self.project,self.work,ignore=shutil.ignore_patterns('.git','__pycache__'))
            if os.getuid()==0:
                for path in [self.work,*self.work.rglob('*')]:os.chown(path,1000,1000)
            self.log=open(self.root/'server.log','w+')
            script="from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler;from functools import partial;import sys;s=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=sys.argv[1]));print(s.server_port,flush=True);s.serve_forever()"
            self.process=subprocess.Popen([sys.executable,'-c',script,str(self.work)],stdout=subprocess.PIPE,stderr=self.log,text=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
            if not select.select([self.process.stdout],[],[],10)[0]:raise RuntimeError('Benchmark static server did not announce its port')
            port=self.process.stdout.readline().strip()
            if not port.isdigit():raise RuntimeError('Benchmark static server startup failed')
            self.url='http://127.0.0.1:'+port;return self
        except BaseException:self.__exit__(None,None,None);raise
    def __exit__(self,*_):
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
            self.process.stdout.close();self.process=None
        if self.log:self.log.close();self.log=None
        if self.work.exists():subprocess.run([sys.executable,'-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(self.work)],check=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        self.temp.cleanup()

def open_page(page,site):
    page.goto(site.url)
    page.wait_for_function('navigator.serviceWorker.controller!==null',timeout=10000)

def create(page,label='Local journal'):
    page.locator('#label').fill(label);page.locator('#create-form button').click();page.locator('#workspace').wait_for(state='visible');return page.locator('#profile-select').input_value()

def plan(page,inputs):
    return page.evaluate("async(input)=>{const m=await import('/src/cycle-planner.js');const before=JSON.stringify(input);const result=m.buildCyclePlan(input);return {result,immutable:before===JSON.stringify(input)};}",inputs)

def notifications(page):
    return page.evaluate("async()=>{const r=await navigator.serviceWorker.ready;return (await r.getNotifications()).map(n=>({title:n.title,body:n.body,tag:n.tag,data:n.data}));}")
