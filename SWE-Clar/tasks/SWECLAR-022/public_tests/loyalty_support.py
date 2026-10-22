"""Public transport, disposable app and prepared-service support; no hidden rules."""
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

PUBLIC = Path(__file__).resolve().parent


class CandidateFailure(AssertionError):
    pass


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def identity(uid):
    return {'user': uid, 'group': uid, 'extra_groups': []} if os.geteuid() == 0 else {}


def run_as(uid, code, *args):
    if os.geteuid() not in (0, uid):
        raise PermissionError('Requested service identity is manager-only')
    return subprocess.run([sys.executable, '-I', '-c', code, *map(str, args)],
                          **identity(uid), check=True, capture_output=True, text=True, timeout=30).stdout


def request(app, path, body=None, token=None, method=None, raw=False):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        response = urlopen(Request(app.url + path, data=data, headers=headers,
                                  method=method or ('GET' if body is None else 'POST')), timeout=35)
    except HTTPError as error:
        response = error
    except (OSError, URLError) as error:
        raise CandidateFailure('Candidate HTTP request failed: ' + str(error)) from error
    with response:
        content = response.read()
        try:
            return {'status': response.status, 'body': content if raw else json.loads(content), 'content_type': response.headers.get('Content-Type')}
        except (ValueError, UnicodeDecodeError) as error:
            raise CandidateFailure('Candidate response is not valid JSON') from error


def ready(url, process):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(url + '/health', timeout=1) as response:
                if response.status == 200 and json.load(response).get('ok') is True:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(.05)
    return False


class Application:
    def __init__(self, project=None, fixture=None):
        self.source = Path(project or os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))
        self.root = Path(tempfile.mkdtemp(prefix='loyalty-session-'))
        self.root.chmod(0o755)
        self.project = self.root / 'work'
        shutil.copytree(self.source, self.project, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', 'data', '.pytest_cache'))
        if os.geteuid() == 0:
            for path in [*self.project.rglob('*'), self.project]:
                if path.is_symlink():
                    raise ValueError('Symlinked candidate material needs containment review')
                os.chown(path, 1000, 1000)
        self.fixture = self.root / 'catalog.json'
        self.seed = fixture or json.loads((PUBLIC / 'catalog.json').read_text())
        self.fixture.write_text(json.dumps(self.seed))
        self.clock = self.root / 'clock.json'
        self.clock.write_text((PUBLIC / 'clock.json').read_text())
        self.process = self.log = None
        self.port = free_port()
        self.url = 'http://127.0.0.1:' + str(self.port)

    def start(self):
        self.log = (self.root / 'server.log').open('ab')
        self.process = subprocess.Popen([sys.executable, 'server.py', '--host', '127.0.0.1', '--port', str(self.port),
            '--db', str(self.project / 'data/loyalty.sqlite3'),
            '--fixture', str(self.fixture), '--clock', str(self.clock)],
            cwd=self.project, env={'PATH': os.environ['PATH'], 'HOME': str(self.project), 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=self.log, stderr=self.log, **identity(1000))
        if not ready(self.url, self.process):
            self.stop()
            raise CandidateFailure('Candidate server failed startup after independent environment preflight')
        return self

    def set_clock(self, now):
        self.clock.write_text(json.dumps({'now': now}))

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
        run_as(1000, "import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()) for x in p.iterdir()]", self.project)
        shutil.rmtree(self.root)


@contextmanager
def browser_session():
    home = Path(tempfile.mkdtemp(prefix='loyalty-browser-'))
    home.chmod(0o755)
    downloads = home / 'downloads'
    downloads.mkdir()
    if os.geteuid() == 0:
        os.chown(home, 1000, 1000)
        os.chown(downloads, 1000, 1000)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, downloads_path=str(downloads),
                executable_path=str(PUBLIC / 'browser_launch.py'),
                env={'PATH': os.environ['PATH'], 'HOME': str(home), 'ARENA_CHROMIUM_BINARY': playwright.chromium.executable_path})
            try:
                yield browser
            finally:
                browser.close()
    finally:
        cleanup = """import json,pathlib,shutil,sys
home=pathlib.Path(sys.argv[1]);marker=home/'profile-location.json'
if marker.exists():
 p=pathlib.Path(json.loads(marker.read_text()))
 if p.parent==pathlib.Path('/tmp') and p.name.startswith('playwright_') and not p.is_symlink():shutil.rmtree(p,ignore_errors=True)
shutil.rmtree(home)
"""
        run_as(1000, cleanup, home)
