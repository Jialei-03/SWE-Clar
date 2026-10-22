"""Public observation adapter for actual Flutter widgets and local HTTP services.

No business expected values live here. Each UI operation is sent separately;
future operations and evaluator assertions never enter the Flutter process.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
MAX_OBSERVATION = 16 * 1024 * 1024


class CandidateFailure(AssertionError):
    pass


class EnvironmentFailure(RuntimeError):
    pass


def http(origin, method, path, body=None, token=None):
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        raise ValueError('Use a relative service path beginning with one slash')
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(origin + path, data=payload, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    except OSError as exc:
        raise CandidateFailure('Application HTTP request did not complete: ' + str(exc)) from exc
    with response:
        raw = response.read(MAX_OBSERVATION + 1)
        if len(raw) > MAX_OBSERVATION:
            raise CandidateFailure('Application HTTP reply exceeds the observation limit')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise CandidateFailure('Application did not return JSON') from exc
        return {'status': response.status, 'body': result}


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def reply(handler, value, status=200):
    data = json.dumps(value, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass


class Proxy:
    """Forward real traffic; optionally lose or hold one completed response."""
    def __init__(self, target):
        self.target = target
        self.lock = threading.Lock()
        self.fault = None
        self.held = threading.Event()
        self.release = threading.Event()
        self.drop_held = False
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def dispatch(self):
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= length <= 32768:
                        return reply(self, {'error': 'invalid_transport_size'}, 400)
                    raw = self.rfile.read(length) if length else None
                    body = json.loads(raw) if raw else None
                    authorization = self.headers.get('Authorization', '')
                    token = authorization[7:] if authorization.startswith('Bearer ') else None
                    with owner.lock:
                        fault = owner.fault if owner.fault and owner.fault['path'] == self.path and owner.fault['method'] == self.command else None
                        if fault:
                            owner.fault = None
                    result = http(owner.target, self.command, self.path, body, token)
                    trace = {'method': self.command, 'path': self.path, 'body': body,
                             'status': result['status'], 'response_lost': False, 'held': bool(fault and fault['hold'])}
                    with owner.lock:
                        owner.requests.append(trace)
                    if fault and fault['hold']:
                        owner.held.set()
                        if not owner.release.wait(20):
                            raise EnvironmentFailure('Held response was not released within 20 seconds')
                    drop = bool(fault) and (not fault['hold'] or owner.drop_held)
                    trace['response_lost'] = drop
                    if drop:
                        self.close_connection = True
                        try:
                            self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        self.connection.close()
                    else:
                        reply(self, result['body'], result['status'])
                except Exception as exc:
                    reply(self, {'error': 'observation_proxy_error', 'detail': str(exc)}, 502)

            do_GET = dispatch
            do_POST = dispatch

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def lose_next(self, path, method='POST', hold=False):
        with self.lock:
            if self.fault is not None or (self.held.is_set() and not self.release.is_set()):
                raise ValueError('Resolve the previous response fault first')
            self.held.clear()
            self.release.clear()
            self.drop_held = False
            self.fault = {'path': path, 'method': method, 'hold': bool(hold)}

    def release_response(self, drop=False):
        if not self.held.wait(15):
            raise CandidateFailure('Application did not send the expected held request')
        self.drop_held = bool(drop)
        self.release.set()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class Control:
    """One operation at a time, without loading private test files in Dart."""
    def __init__(self):
        self.token = secrets.token_hex(32)
        self.inbox = queue.Queue(maxsize=1)
        self.outbox = queue.Queue(maxsize=1)
        self.ready = threading.Event()
        self.closed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def allowed(self):
                return self.headers.get('Authorization') == 'Bearer ' + owner.token

            def do_GET(self):
                if not self.allowed():
                    return reply(self, {'error': 'unauthorized'}, 401)
                if self.path != '/next':
                    return reply(self, {'error': 'not_found'}, 404)
                owner.ready.set()
                while not owner.closed:
                    try:
                        return reply(self, owner.inbox.get(timeout=.5))
                    except queue.Empty:
                        continue
                reply(self, {'op': 'close'})

            def do_POST(self):
                if not self.allowed():
                    return reply(self, {'error': 'unauthorized'}, 401)
                length = int(self.headers.get('Content-Length', '0'))
                if self.path != '/result' or not 0 < length <= MAX_OBSERVATION:
                    return reply(self, {'error': 'invalid_observation'}, 400)
                try:
                    value = json.loads(self.rfile.read(length))
                    owner.outbox.put(value, timeout=5)
                    reply(self, {'received': True})
                except (ValueError, queue.Full):
                    reply(self, {'error': 'invalid_observation'}, 400)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.closed = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ClinicSession:
    def __init__(self, project=None, fixture=None, now_ms=None):
        if os.geteuid() not in (0, 1000):
            raise EnvironmentFailure('Run this adapter inside the prepared benchmark container')
        if not (HERE / 'clinic_driver_test.dart').is_file():
            raise EnvironmentFailure('Protected Flutter operation driver is missing')
        self.identity = {'user': 1000, 'group': 1000, 'extra_groups': []} if os.geteuid() == 0 else {}
        self.root = Path(tempfile.mkdtemp(prefix='sweclar-clinic-'))
        self.root.chmod(0o755)
        self.work = self.root / 'work'
        self.work.mkdir()
        if self.identity:
            os.chown(self.work, 1000, 1000)
        self.project = self.work / 'project'
        self.environment = {'PATH': os.environ['PATH'], 'HOME': str(self.work / 'home'), 'CI': 'true',
                            'FLUTTER_SUPPRESS_ANALYTICS': 'true'}
        self.logs = []
        self.captures = {}
        self.observations = []
        self.server = None
        self.driver = None
        self.proxy = None
        self.control = None
        self.handles = []
        self.sequence = 0
        self.closed = False
        try:
            source = Path(project or os.environ.get('SWECLAR_PROJECT_DIR', os.getcwd())).resolve()
            script = '''import pathlib,shutil,sys
source=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2])
shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','.dart_tool','build','__pycache__'))
(target.parent/'home').mkdir()
(target.parent/'state').mkdir()
(target.parent/'captures').mkdir()
'''
            self.child([sys.executable, '-I', '-c', script, str(source), str(self.project)], timeout=20)
            self.fixture_path = self.root / 'fixture.json'
            self.clock_path = self.root / 'clock.json'
            if fixture is None:
                fixture = json.loads(self.read(self.project / 'fixtures/clinic.json'))
            if now_ms is None:
                now_ms = json.loads(self.read(self.project / 'fixtures/clock.json'))['now_ms']
            self.fixture_path.write_text(json.dumps(fixture, ensure_ascii=False))
            self.fixture_path.chmod(0o644)
            self.set_clock(now_ms)
            self.database = self.work / 'state/store.sqlite'
            self.backend_port = unused_port()
            self.backend_origin = f'http://127.0.0.1:{self.backend_port}'
            self.start_backend()
            self.proxy = Proxy(self.backend_origin)
        except Exception:
            self.close()
            raise

    def child(self, command, cwd=None, timeout=60, log_output=True):
        try:
            result = subprocess.run(command, cwd=cwd, env=self.environment, **self.identity,
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise CandidateFailure('Candidate command exceeded the published limit') from exc
        self.logs.append({'command': command, 'returncode': result.returncode,
                          'stdout': result.stdout[-6000:] if log_output else '<binary observation transport>', 'stderr': result.stderr[-6000:]})
        if result.returncode:
            raise CandidateFailure('Candidate command failed: ' + str(command) + '\n' + (result.stdout + result.stderr)[-3500:])
        return result.stdout

    def read(self, path):
        script = '''import pathlib,base64,sys
data=pathlib.Path(sys.argv[1]).read_bytes()
if len(data)>16*1024*1024:raise ValueError('Observation exceeds 16 MiB')
print(base64.b64encode(data).decode())
'''
        return base64.b64decode(self.child([sys.executable, '-I', '-c', script, str(path)], timeout=10, log_output=False).strip(), validate=True)

    def log_handle(self, name):
        handle = (self.root / name).open('w+')
        self.handles.append(handle)
        return handle

    def set_clock(self, now_ms):
        if type(now_ms) is not int or not 0 <= now_ms <= 4102444800000:
            raise ValueError('Clock must be a supported integer UTC millisecond instant')
        pending = self.root / 'clock.pending'
        pending.write_text(json.dumps({'now_ms': now_ms}))
        pending.chmod(0o644)
        pending.replace(self.root / 'clock.json')

    def start_backend(self):
        self.backend_out = self.log_handle(f'backend-{len(self.logs)}.stdout')
        self.backend_err = self.log_handle(f'backend-{len(self.logs)}.stderr')
        command = [sys.executable, 'server/main.py', '--fixture', str(self.fixture_path),
                   '--db', str(self.database), '--clock-file', str(self.clock_path), '--port', str(self.backend_port)]
        self.server = subprocess.Popen(command, cwd=self.project, env=self.environment, **self.identity,
                                       stdout=self.backend_out, stderr=self.backend_err, text=True)
        for _ in range(160):
            if self.server.poll() is not None:
                self.backend_err.seek(0)
                raise CandidateFailure('Candidate service exited: ' + self.backend_err.read()[-3500:])
            try:
                result = http(self.backend_origin, 'GET', '/health')
                if result['status'] == 200:
                    return
            except CandidateFailure:
                pass
            time.sleep(.05)
        raise CandidateFailure('Candidate service did not become responsive on its provided port')

    def stop_process(self, process, label):
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self.logs.append({'process': label, 'terminal_returncode': process.returncode})

    def restart_backend(self):
        self.stop_process(self.server, 'backend restart')
        self.start_backend()

    def api(self, method, path, body=None, token=None):
        return http(self.backend_origin, method, path, body, token)

    def parallel_api(self, requests):
        if not 1 <= len(requests) <= 16:
            raise ValueError('Use one to sixteen concurrent requests')
        barrier = threading.Barrier(len(requests))
        def request(row):
            barrier.wait(timeout=5)
            return self.api(row['method'], row['path'], row.get('body'), row.get('token'))
        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            return list(executor.map(request, requests))

    def storage_readonly(self, value):
        # Apply the same real Unix permissions as the application's own identity.
        # No knowledge of the application's SQLite schema is required.
        self.child([sys.executable, '-I', '-c',
                    'import pathlib,sys;p=pathlib.Path(sys.argv[1]);ro=sys.argv[2]=="1";'
                    'p.chmod(0o555 if ro else 0o755);'
                    '[(x.chmod(0o444 if ro else 0o644)) for x in p.iterdir() if x.is_file()]',
                    str(self.work / 'state'), '1' if value else '0'])

    def start_driver(self):
        if self.driver is not None:
            return
        self.child(['flutter', 'pub', 'get', '--offline', '--enforce-lockfile'], cwd=self.project)
        self.control = Control()
        self.driver_out = self.log_handle(f'driver-{self.sequence}.stdout')
        self.driver_err = self.log_handle(f'driver-{self.sequence}.stderr')
        environment = {**self.environment, 'CLINIC_ORIGIN': self.proxy.origin,
                       'CLINIC_CONTROL_ORIGIN': self.control.origin, 'CLINIC_CONTROL_TOKEN': self.control.token}
        self.driver = subprocess.Popen(['flutter', 'test', '--no-pub', '--reporter', 'expanded', str(HERE / 'clinic_driver_test.dart')],
                                      cwd=self.project, env=environment, **self.identity,
                                      stdout=self.driver_out, stderr=self.driver_err, text=True)
        for _ in range(600):
            if self.control.ready.wait(.05):
                return
            if self.driver.poll() is not None:
                self.driver_out.seek(0); self.driver_err.seek(0)
                raise CandidateFailure('Flutter driver could not load the candidate: ' + (self.driver_out.read() + self.driver_err.read())[-4000:])
        raise CandidateFailure('Flutter driver startup exceeded 30 seconds')

    def ui(self, operation):
        if operation['op'] == 'reopen_client':
            previous_pid = self.driver.pid if self.driver is not None else None
            if self.control is not None:
                self.control.close()
                if self.driver.poll() is None:
                    try:
                        self.driver.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                self.stop_process(self.driver, 'Flutter client reopen')
            self.driver = None
            self.control = None
            result = self.ui({'op': 'mount'})
            result['op'] = 'reopen_client'
            result['fresh_process'] = previous_pid != self.driver.pid
            return result
        self.start_driver()
        operation = json.loads(json.dumps(operation))
        self.sequence += 1
        operation['sequence'] = self.sequence
        if operation['op'] == 'capture':
            name = operation.get('name')
            if not isinstance(name, str) or Path(name).name != name or not name.endswith('.png') or name in self.captures:
                raise ValueError('Capture needs a distinct PNG basename')
            operation['path'] = str(self.work / 'captures' / name)
        self.control.inbox.put(operation, timeout=5)
        deadline = time.monotonic() + 35
        while True:
            try:
                result = self.control.outbox.get(timeout=.2)
                break
            except queue.Empty:
                if self.driver.poll() is not None:
                    self.driver_out.seek(0); self.driver_err.seek(0)
                    raise CandidateFailure('Flutter session exited while handling an operation: ' + (self.driver_out.read() + self.driver_err.read())[-4000:])
                if time.monotonic() > deadline:
                    raise CandidateFailure('Flutter operation exceeded 35 seconds')
        if result.get('sequence') != self.sequence or result.get('op') != operation['op']:
            raise CandidateFailure('Flutter observation order differs from submitted operations')
        if result.get('operation_error') or result.get('render_errors'):
            raise CandidateFailure('Flutter operation/render failed: ' + json.dumps(result))
        if operation['op'] == 'capture':
            png = self.read(Path(operation['path']))
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise CandidateFailure('Flutter capture is not a PNG')
            self.captures[operation['name']] = base64.b64encode(png).decode()
        self.observations.append(result)
        return result

    def operate(self, operation):
        kind = operation['op']
        if kind == 'api':
            return {'op': kind, **self.api(operation['method'], operation['path'], operation.get('body'), operation.get('token'))}
        if kind == 'parallel_api':
            return {'op': kind, 'results': self.parallel_api(operation['requests'])}
        if kind == 'restart_backend':
            self.restart_backend()
        elif kind == 'set_clock':
            self.set_clock(operation['now_ms'])
        elif kind == 'drop_next_response':
            self.proxy.lose_next(operation['path'], operation.get('method', 'POST'), operation.get('hold', False))
        elif kind == 'release_response':
            self.proxy.release_response(operation.get('drop', False))
        elif kind == 'storage_readonly':
            self.storage_readonly(bool(operation['value']))
        else:
            return self.ui(operation)
        return {'op': kind, 'completed': True}

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.proxy:
            self.proxy.release.set()
        if self.control:
            self.control.close()
            if self.driver is not None and self.driver.poll() is None:
                try:
                    self.driver.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        self.stop_process(self.driver, 'Flutter driver')
        self.stop_process(self.server, 'backend')
        if self.proxy:
            self.proxy.close()
        for handle in self.handles:
            handle.close()
        if self.work.exists():
            script = '''import pathlib,shutil,sys,os
root=pathlib.Path(sys.argv[1]);root.chmod(0o755)
for parent,dirs,files in os.walk(root,followlinks=False):
 for name in dirs:
  p=pathlib.Path(parent)/name
  if not p.is_symlink():p.chmod(0o755)
for p in root.iterdir():
 if p.is_dir() and not p.is_symlink():shutil.rmtree(p)
 else:p.unlink()
'''
            cleaned = subprocess.run([sys.executable, '-I', '-c', script, str(self.work)],
                                     env=self.environment, **self.identity, capture_output=True, text=True)
            self.logs.append({'process': 'candidate storage cleanup', 'returncode': cleaned.returncode, 'stderr': cleaned.stderr})
            if cleaned.returncode:
                raise EnvironmentFailure('Adapter cleanup failed: ' + cleaned.stderr[-2500:])
            # The candidate cannot remove an entry from its protected parent.
            # Only the manager removes this now-empty directory and the clock.
            self.work.rmdir()
        shutil.rmtree(self.root)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def resolve(value, saved):
    if isinstance(value, dict) and set(value) == {'$ref'}:
        result = saved
        for part in value['$ref'].split('.'):
            result = result[int(part)] if isinstance(result, list) else result[part]
        return result
    if isinstance(value, dict) and set(value) == {'$concat'}:
        return ''.join(str(resolve(part, saved)) for part in value['$concat'])
    if isinstance(value, dict):
        return {key: resolve(item, saved) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, saved) for item in value]
    return value


def run_session(script, project=None):
    results, saved = [], {}
    with ClinicSession(project=project, fixture=script.get('fixture'), now_ms=script.get('now_ms')) as session:
        for operation in script['operations']:
            operation = resolve(operation, saved)
            result = session.operate(operation)
            results.append(result)
            if operation.get('save_as'):
                saved[operation['save_as']] = result
        return {'observations': results, 'captures_base64': session.captures,
                'http_trace': session.proxy.requests, 'logs': session.logs}
