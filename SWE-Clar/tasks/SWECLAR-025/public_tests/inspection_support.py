"""Public disposable PHP service runner; no hidden rules or test oracles."""
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
        self.config=dict(config or json.loads((Path(__file__).parent/'development.json').read_text()))
        (self.project/'runtime').mkdir(exist_ok=True)
        self.config_file=self.project/'runtime/config.json'
        self.config_file.write_text(json.dumps(self.config))
        self.config_file.chmod(0o600)
        if os.geteuid()==0:
            for path in [*self.project.rglob('*'),self.project]:os.chown(path,1000,1000)
        self.process=self.log=None

    def start(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.url='http://127.0.0.1:'+str(port)
        env={'PATH':os.environ['PATH'],'HOME':str(self.project),
             'INSPECTION_CONFIG':str(self.config_file),'INSPECTION_DB':str(self.project/'runtime/records.sqlite'),
             'PHP_CLI_SERVER_WORKERS':'4'}
        self.log=(self.root/'server.log').open('ab')
        self.process=subprocess.Popen(['php','-S','127.0.0.1:'+str(port),'-t','web','router.php'],cwd=self.project,env=env,
            stdout=subprocess.PIPE,stderr=self.log,start_new_session=True,**identity())
        try:
            deadline=time.monotonic()+10
            while True:
                if self.process.poll() is not None:raise RuntimeError('PHP server exited')
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.url+'/api/context',timeout=.5) as response:break
                except urllib.error.HTTPError as error:
                    if error.code==401:break
                    raise
                except OSError:
                    if time.monotonic()>deadline:raise RuntimeError('PHP server startup timed out')
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
