"""Run the supplied service in a disposable workspace as the candidate user."""
import json,os,shutil,signal,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path

def identity():
    return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}

class Application:
    def __init__(self, seed, source=None):
        self.root=Path(tempfile.mkdtemp(prefix='control-'));self.root.chmod(0o755)
        self.project=self.root/'work'
        source=Path(source or os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()))
        if any(p.is_symlink() for p in source.rglob('*')):raise ValueError('Symlink in workspace')
        shutil.copytree(source,self.project,ignore=shutil.ignore_patterns('runtime','.git','__pycache__','*.pyc'))
        runtime=self.project/'runtime';runtime.mkdir()
        (runtime/'seed.json').write_text(json.dumps(seed))
        if os.geteuid()==0:
            for p in [self.project,*self.project.rglob('*')]:os.chown(p,1000,1000)
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        self.process=None
    def request(self,path,data=None):
        r=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(r,timeout=5) as response:return json.load(response)
    def start(self):
        self.process=subprocess.Popen([sys.executable,'server.py','--db','runtime/state.db','--seed','runtime/seed.json','--port',str(self.port)],cwd=self.project,env={'PATH':os.environ['PATH'],'HOME':str(self.project/'runtime'),'PYTHONDONTWRITEBYTECODE':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,**identity())
        for _ in range(100):
            if self.process.poll() is not None:raise RuntimeError('Candidate server exited')
            try:
                if self.request('/health').get('ok') is True:return self
            except OSError:pass
            time.sleep(.03)
        raise RuntimeError('Candidate startup timeout')
    def stop(self):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGTERM)
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
    def restart(self):self.stop();return self.start()
    def close(self):
        self.stop()
        subprocess.run([sys.executable,'-I','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]',str(self.project)],check=True,**identity())
        shutil.rmtree(self.root)
    def __enter__(self):
        try:return self.start()
        except BaseException:self.close();raise
    def __exit__(self,*args):self.close()
