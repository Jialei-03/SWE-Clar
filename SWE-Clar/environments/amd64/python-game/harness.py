"""Protected process support; no task answers or grading cases belong here."""
import json
import os
import select
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CandidateFailure(AssertionError):
    pass


class App:
    def __init__(self, project, arguments=None):
        self.project = Path(project)
        self.arguments = list(arguments or [])
        self.temp = tempfile.TemporaryDirectory(prefix='sweclar-test-')
        if os.geteuid() == 0:
            os.chmod(self.temp.name, 0o777)
        self.db = Path(self.temp.name) / 'state.sqlite'
        self.process = None
        self.log = None

    def start(self):
        self.log = open(Path(self.temp.name) / 'server.log', 'a+')
        identity = {'user':1000, 'group':1000, 'extra_groups':[]} if os.geteuid() == 0 else {}
        self.process = subprocess.Popen([sys.executable, 'server.py', '--port', '0', '--db', str(self.db)] + self.arguments,
                                        cwd=self.project, stdout=subprocess.PIPE, stderr=self.log, text=True,
                                        env={'PATH':os.environ['PATH'], 'HOME':self.temp.name, 'PYTHONDONTWRITEBYTECODE':'1'}, **identity)
        if not select.select([self.process.stdout], [], [], 10)[0]:
            raise CandidateFailure('Candidate did not announce its port within 10s after environment preflight')
        try:
            line = self.process.stdout.readline()
            self.url = 'http://127.0.0.1:' + str(int(json.loads(line)['port']))
        except (ValueError, KeyError, TypeError) as error:
            self.log.flush()
            self.log.seek(0)
            raise CandidateFailure('Candidate startup failed: ' + self.log.read()[-2000:]) from error
        return self

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdout.close()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def __exit__(self, *_):
        self.stop()
        self.temp.cleanup()

    def request(self, path, body=None, status=200, raw=False):
        headers = {}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        elif isinstance(body, str):
            body = body.encode()
            headers['Content-Type'] = 'text/csv'
        try:
            response = urlopen(Request(self.url + path, data=body, headers=headers), timeout=10)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, ConnectionError) as error:
            raise CandidateFailure('Candidate HTTP operation failed: ' + str(error)) from error
        with response:
            text = response.read().decode()
            if response.code != status:
                raise CandidateFailure(f'{path}: expected HTTP {status}, got {response.code}: {text[:300]}')
        if raw:
            return text
        try:
            return json.loads(text)
        except ValueError as error:
            raise CandidateFailure('Candidate returned invalid JSON') from error
