"""Public HTTP/browser/controlled-clock support; no hidden rules or assertions."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright


class CandidateFailure(AssertionError):
    pass


def request(app, path, body=None, token=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None if body is None else json.dumps(body).encode()
    try:
        response = urlopen(Request(app.url + path, data=data, headers=headers, method=method or ('GET' if body is None else 'POST')), timeout=10)
    except HTTPError as error:
        response = error
    except (OSError, URLError) as error:
        raise CandidateFailure('Candidate HTTP request failed: ' + str(error)) from error
    with response:
        raw = response.read()
        try:
            return {'status': response.status, 'body': json.loads(raw)}
        except (ValueError, UnicodeDecodeError) as error:
            raise CandidateFailure('Candidate returned incompatible JSON') from error


class Application:
    def __init__(self, project=None):
        self.source = Path(project or os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))
        self.root = Path(tempfile.mkdtemp(prefix='lattice-session-'))
        self.root.chmod(0o755)
        self.project = self.root / 'work'
        shutil.copytree(self.source, self.project, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', '.pytest_cache'))
        if os.geteuid() == 0:
            for p in [*self.project.rglob('*'), self.project]:
                if p.is_symlink():
                    raise ValueError('Symlinked candidate material needs containment review')
                os.chown(p, 1000, 1000)
        self.process = None
        self.log = None

    def start(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.url = 'http://127.0.0.1:' + str(port)
        self.log = (self.root / 'server.log').open('ab')
        identity = {'user': 1000, 'group': 1000, 'extra_groups': []} if os.geteuid() == 0 else {}
        self.process = subprocess.Popen([sys.executable, 'server.py', '--port', str(port)],
            cwd=self.project, stdout=self.log, stderr=self.log,
            env={'PATH': os.environ['PATH'], 'HOME': str(self.project), 'PYTHONDONTWRITEBYTECODE': '1'}, **identity)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise CandidateFailure('Candidate server terminated during startup')
            try:
                if request(self, '/health')['status'] == 200:
                    return self
            except CandidateFailure:
                pass
            time.sleep(.05)
        raise CandidateFailure('Candidate server did not become ready after environment preflight')

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
            self.process = None
        if self.log:
            self.log.close(); self.log = None

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        self.stop()
        identity = {'user': 1000, 'group': 1000, 'extra_groups': []} if os.geteuid() == 0 else {}
        # Clear candidate-owned content as its owner, then remove the parent entry.
        code = "import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()) for x in p.iterdir()]"
        subprocess.run([sys.executable, '-I', '-c', code, str(self.project)], **identity, check=True, capture_output=True)
        shutil.rmtree(self.root)


@contextmanager
def browser_session():
    temp = tempfile.mkdtemp(prefix='lattice-browser-')
    downloads = Path(temp) / 'downloads'
    downloads.mkdir()
    Path(temp).chmod(0o755)
    if os.geteuid() == 0:
        os.chown(downloads, 1000, 1000)
        os.chown(temp, 1000, 1000)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, downloads_path=str(downloads), executable_path=str(Path(__file__).with_name('browser_launch.py')),
                env={'PATH': os.environ['PATH'], 'HOME': temp, 'ARENA_CHROMIUM_BINARY': p.chromium.executable_path})
            try:
                yield browser
            finally:
                browser.close()
    finally:
        identity = {'user': 1000, 'group': 1000, 'extra_groups': []} if os.geteuid() == 0 else {}
        cleanup = """import json,pathlib,shutil,sys
home=pathlib.Path(sys.argv[1]);marker=home/'profile-location.json'
if marker.exists():
 p=pathlib.Path(json.loads(marker.read_text()))
 if p.parent==pathlib.Path('/tmp') and p.name.startswith('playwright_') and not p.is_symlink():shutil.rmtree(p,ignore_errors=True)
shutil.rmtree(home)
"""
        subprocess.run([sys.executable,'-I','-c',cleanup,temp],**identity,check=True,capture_output=True)


def read_download(download):
    """Read actual Chromium output as its owner, without broadening permissions."""
    path = download.path()
    identity = {'user': 1000, 'group': 1000, 'extra_groups': []} if os.geteuid() == 0 else {}
    result = subprocess.run([sys.executable, '-I', '-c',
        'import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())', path],
        capture_output=True, check=True, timeout=10, **identity)
    return result.stdout
