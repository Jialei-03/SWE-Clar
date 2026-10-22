"""Public disposable CLI and manager-owned adapter support, without business oracle."""
import json,os,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
PUBLIC=Path(__file__).resolve().parent

class CandidateFailure(AssertionError):pass

def identity(uid):return {'user':uid,'group':uid,'extra_groups':[]} if os.geteuid()==0 else {}

def run_as(uid,code,*args):
    if os.geteuid() not in (0,uid):raise PermissionError('Manager-owned identity')
    return subprocess.run([sys.executable,'-I','-c',code,*map(str,args)],**identity(uid),capture_output=True,text=True,check=True,timeout=30).stdout

class AdapterService:
    def __init__(self,port=None):
        if os.geteuid()!=0:raise PermissionError('Benchmark prepares adapter before budget')
        self.root=Path(tempfile.mkdtemp(prefix='pipeline-adapter-'));self.root.chmod(0o755)
        self.state=self.root/'state';self.state.mkdir();os.chown(self.state,2000,2000)
        run_as(2000,'import os,sys;os.chmod(sys.argv[1],0o700)',self.state)
        if port is None:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.port=port;self.url='http://127.0.0.1:'+str(port);self.process=None
    def configure(self,mode='normal'):
        run_as(2000,"import json,pathlib,sys;pathlib.Path(sys.argv[1],'controls.json').write_text(json.dumps({'mode':sys.argv[2]}))",self.state,mode)
    def start(self):
        self.process=subprocess.Popen([sys.executable,'-I',str(PUBLIC/'adapter_fixture.py'),'--state',str(self.state),'--port',str(self.port)],user=2000,group=2000,extra_groups=[],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(200):
            if self.process.poll() is not None:raise RuntimeError('Prepared adapter exited')
            try:
                with urlopen(self.url+'/health',timeout=1) as response:
                    if json.load(response).get('ok') is True:return self
            except OSError:pass
            time.sleep(.05)
        self.close();raise RuntimeError('Prepared adapter unavailable')
    def requests(self):
        return json.loads(run_as(2000,"import sqlite3,json,sys;db=sqlite3.connect(sys.argv[1]);print(json.dumps(db.execute('SELECT method,path,header,envelope FROM requests ORDER BY rowid').fetchall()))",self.state/'adapter.sqlite3'))
    def reset(self):
        run_as(2000,"import sqlite3,sys;db=sqlite3.connect(sys.argv[1]);db.execute('DELETE FROM receipts');db.execute('DELETE FROM requests');db.commit()",self.state/'adapter.sqlite3');self.configure()
    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
        run_as(2000,"import pathlib,sys;p=pathlib.Path(sys.argv[1]);[x.unlink() for x in p.iterdir()];p.chmod(0o755)",self.state)
        self.state.rmdir();self.root.rmdir()
    def __enter__(self):return self.start()
    def __exit__(self,*_):self.close()

class Pipeline:
    def __init__(self,project=None,adapter='http://127.0.0.1:8081'):
        self.source=Path(project or os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
        self.root=Path(tempfile.mkdtemp(prefix='pipeline-attempt-'));self.root.chmod(0o755)
        self.project=self.root/'work';shutil.copytree(self.source,self.project,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.git','data'))
        if os.geteuid()==0:
            for p in [self.project,*self.project.rglob('*')]:
                if p.is_symlink():raise ValueError('Candidate symlink requires containment review')
                os.chown(p,1000,1000)
        self.adapter=adapter;self.db=self.project/'data/pipeline.sqlite3'
    def run(self,commands=None,raw=None):
        data=raw if raw is not None else ''.join(json.dumps(c,ensure_ascii=True)+'\n' for c in commands).encode()
        try:
            result=subprocess.run([sys.executable,'cli.py','--db',str(self.db),'--adapter',self.adapter],cwd=self.project,input=data,capture_output=True,timeout=90,env={'PATH':os.environ['PATH'],'HOME':str(self.project),'PYTHONDONTWRITEBYTECODE':'1'},**identity(1000))
        except subprocess.TimeoutExpired as error:raise CandidateFailure('CLI exceeded public command budget') from error
        if result.returncode:raise CandidateFailure('CLI failed: '+result.stderr.decode(errors='replace')[-1200:])
        try:return [json.loads(line) for line in result.stdout.split(b'\n') if line]
        except (ValueError,UnicodeDecodeError) as error:raise CandidateFailure('CLI stdout is not JSON lines') from error
    def read(self,path):return run_as(1000,"import pathlib,sys;sys.stdout.write(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig'))",self.project/path)
    def __enter__(self):return self
    def __exit__(self,*_):
        run_as(1000,"import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()) for x in p.iterdir()]",self.project)
        shutil.rmtree(self.root)
