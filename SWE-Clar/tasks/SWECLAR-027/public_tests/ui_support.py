"""Public isolated React Native Web build and static server helper."""
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import socket
import time
import urllib.request
import urllib.error


def identity():
    return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}


class CandidateFailure(AssertionError):
    pass


class Application:
    def __init__(self, project=None, config=None):
        source=Path(project or os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd())).resolve()
        self.root=Path(tempfile.mkdtemp(prefix='stream-session-'))
        self.root.chmod(0o755)
        self.project=self.root/'work'
        if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
            shutil.rmtree(self.root)
            raise ValueError('Symlinked candidate material requires containment review')
        ignored=shutil.ignore_patterns('__pycache__','*.pyc','.git','.pytest_cache')
        def fresh_material(directory,names):
            return set(ignored(directory,names)) | ({'runtime'} if Path(directory)==source else set())
        shutil.copytree(source,self.project,ignore=fresh_material)
        self.project.chmod(0o755)
        (self.project/'runtime').mkdir(exist_ok=True)
        self.config_file=self.project/'config.json'
        if config is not None:self.config_file.write_text(json.dumps(config))
        self.dist=self.project/'runtime/dist'
        if os.geteuid()==0:
            for path in [*self.project.rglob('*'),self.project]:os.chown(path,1000,1000)
        self.process=self.log=None

    def environment(self):
        env={'PATH':os.environ['PATH'],'HOME':str(self.project/'runtime'),'PYTHONDONTWRITEBYTECODE':'1'}
        for name in ['UI_NODE_MODULES','ESBUILD_BINARY_PATH']:
            if name in os.environ:env[name]=os.environ[name]
        return env

    def build(self):
        result=subprocess.run(['node','build.mjs',str(self.dist)],cwd=self.project,env=self.environment(),
            capture_output=True,text=True,timeout=30,**identity())
        if result.returncode:raise CandidateFailure('Candidate build failed: '+result.stderr[-2000:])
        return result

    def start(self):
        if not self.dist.exists():self.build()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.url='http://127.0.0.1:'+str(port)
        self.log=(self.root/'server.log').open('ab')
        self.process=subprocess.Popen([sys.executable,'-m','http.server',str(port),'--bind','127.0.0.1','--directory',str(self.dist)],cwd=self.project,env=self.environment(),
            stdout=subprocess.PIPE,stderr=self.log,start_new_session=True,**identity())
        try:
            deadline=time.monotonic()+10
            while True:
                if self.process.poll() is not None:raise RuntimeError('Static server exited')
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.url,timeout=.5) as response:
                        if response.status==200:break
                except OSError:
                    if time.monotonic()>deadline:raise RuntimeError('Static server startup timed out')
                    time.sleep(.05)
            return self
        except BaseException:
            self.stop();raise

    def stop(self):
        if self.process:
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL)
                self.process.wait(timeout=5)
            # Reap residual members even if the main candidate exited first.
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            self.process.stdout.close()
            self.process=None
        if self.log:self.log.close();self.log=None

    def close(self):
        self.stop()
        cleanup='''import pathlib,shutil,sys,json
p=pathlib.Path(sys.argv[1])
marker=p/'runtime/profile-location.json'
if marker.exists():
 profile=pathlib.Path(json.loads(marker.read_text()))
 if profile.parent==pathlib.Path('/tmp') and profile.name.startswith('playwright_') and not profile.is_symlink():shutil.rmtree(profile,ignore_errors=True)
[(shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()) for x in p.iterdir()]
'''
        subprocess.run([sys.executable,'-I','-c',cleanup,str(self.project)],**identity(),check=True,capture_output=True,timeout=20)
        shutil.rmtree(self.root)

    def __enter__(self):
        try:return self.start()
        except BaseException:self.close();raise

    def __exit__(self,*_):self.close()
