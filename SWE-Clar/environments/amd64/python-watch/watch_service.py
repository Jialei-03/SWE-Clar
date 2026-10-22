"""Independent synthetic pages and canonical subscription receipts for local tasks.

The evaluator controls its own instance directly in memory. Only the disposable
development instance enables the documented, deliberately public demo controls.
This module contains no hidden input, customer material, secret or grading rule.
"""
import argparse
import copy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit


ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


@dataclass(frozen=True)
class Resource:
    body: bytes
    status: int = 200
    content_type: str = 'text/html; charset=utf-8'
    headers: tuple = ()
    entered: object = None
    release: object = None


class WatchService:
    def __init__(self, fixtures=None, *, demo=False, port=0):
        self.demo = demo
        self._initial = copy.deepcopy(fixtures or {'pages': {}, 'receipts': []})
        self._lock = threading.RLock()
        self._pages = {}
        self._receipts = {}
        self._requests = []
        self._resources = []
        self.reset()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *_):
                pass

            def respond(self, resource):
                if resource.entered is not None:
                    resource.entered.set()
                if resource.release is not None and not resource.release.wait(20):
                    resource = Resource(b'{"error":"owner_hold_expired"}', 503, 'application/json')
                try:
                    self.send_response(resource.status)
                    self.send_header('Content-Type', resource.content_type)
                    self.send_header('Content-Length', str(len(resource.body)))
                    self.send_header('Cache-Control', 'no-store')
                    for key, value in resource.headers:
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(resource.body)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    # Deliberately failed/oversized resources may be closed by clients.
                    pass

            def payload(self, status, body):
                return self.respond(Resource(json.dumps(body).encode('utf-8'), status, 'application/json'))

            def note(self):
                with owner._lock:
                    owner._requests.append({'method': self.command, 'path': self.path})

            def do_GET(self):
                self.note()
                try:
                    path = urlsplit(self.path).path
                except ValueError:
                    return self.payload(400, {'error': 'invalid_path'})
                if path == '/health':
                    return self.payload(200, {'ready': True, 'service': 'synthetic-watch'})
                with owner._lock:
                    if path.startswith('/pages/') and ID.fullmatch(path[7:]):
                        resource = owner._pages.get(path[7:])
                    elif path.startswith('/v1/receipts/') and ID.fullmatch(path[13:]):
                        resource = owner._receipts.get(path[13:])
                    else:
                        resource = None
                if resource is None:
                    return self.payload(404, {'error': 'unknown_resource'})
                return self.respond(resource)

            def do_POST(self):
                self.note()
                # Permission precedes parsing; no candidate-visible control on test instances.
                if not owner.demo:
                    return self.payload(403, {'error': 'private_owner_controls_only'})
                if self.path not in ['/demo/page', '/demo/reset']:
                    return self.payload(404, {'error': 'unknown_resource'})
                try:
                    length_text = self.headers.get('Content-Length', '')
                    if not re.fullmatch(r'[0-9]{1,7}', length_text):
                        raise ValueError('content length')
                    length = int(length_text)
                    if not 0 < length <= 1048576:
                        raise ValueError('body limit')
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError('incomplete body')
                    data = json.loads(body.decode('utf-8'), object_pairs_hook=object_pairs)
                    if not isinstance(data, dict):
                        raise ValueError('object required')
                    if self.path == '/demo/reset':
                        if data:
                            raise ValueError('empty object required')
                        owner.reset()
                    else:
                        if set(data) != {'slug', 'html'}:
                            raise ValueError('fields')
                        if not isinstance(data['slug'], str) or not ID.fullmatch(data['slug']):
                            raise ValueError('slug')
                        if not isinstance(data['html'], str) or not 1 <= len(data['html'].encode('utf-8')) <= 262144:
                            raise ValueError('HTML size')
                        owner.set_page(data['slug'], data['html'])
                except (ValueError, UnicodeError, TypeError, TimeoutError):
                    return self.payload(400, {'error': 'invalid_control_input'})
                return self.payload(200, {'ok': True})

            def do_PUT(self):
                self.note()
                return self.payload(405, {'error': 'unsupported_method'})

            do_PATCH = do_PUT
            do_DELETE = do_PUT

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def reset(self):
        with self._lock:
            self._pages.clear()
            self._receipts.clear()
            for slug, html in self._initial['pages'].items():
                self.set_page(slug, html)
            for receipt in self._initial['receipts']:
                self.set_receipt(receipt['id'], receipt)

    def set_page(self, slug, body, *, status=200, content_type='text/html; charset=utf-8', headers=(), entered=None, release=None):
        if not isinstance(slug, str) or not ID.fullmatch(slug):
            raise ValueError('invalid resource slug')
        if isinstance(body, str):
            body = body.encode('utf-8')
        resource = Resource(bytes(body), status, content_type, tuple(headers), entered, release)
        with self._lock:
            self._pages[slug] = resource
            self._resources.append(resource)

    def set_receipt(self, receipt_id, body, *, status=200, content_type='application/json', headers=(), entered=None, release=None):
        if not isinstance(receipt_id, str) or not ID.fullmatch(receipt_id):
            raise ValueError('invalid receipt ID')
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        resource = Resource(bytes(body), status, content_type, tuple(headers), entered, release)
        with self._lock:
            self._receipts[receipt_id] = resource
            self._resources.append(resource)

    def requests(self):
        with self._lock:
            return copy.deepcopy(self._requests)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        with self._lock:
            for resource in self._resources:
                if resource.release is not None:
                    resource.release.set()
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--port', type=int, default=38920)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    with WatchService(json.loads(args.fixtures.read_text()), demo=args.demo, port=args.port) as service:
        print(json.dumps({'url': service.url, 'demo': args.demo}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
