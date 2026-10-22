"""Loopback transport for an independently constructed three-dimensional portal arena."""
import argparse
from copy import deepcopy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from solution import process_portal_event


def make_server(port=0):
    root = Path(__file__).resolve().parent
    initial = json.loads((root / 'scenario.json').read_text())
    state = deepcopy(initial)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value, content_type='application/json'):
            body = json.dumps(value).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split('?')[0] in ['/', '/game']:
                return self.respond(200, (root / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if self.path == '/health':
                return self.respond(200, {'ok': True})
            if self.path == '/state':
                with lock:
                    return self.respond(200, state)
            self.respond(404, {'error': {'code': 'not_found'}})

        def do_POST(self):
            nonlocal state
            if self.path == '/reset':
                with lock:
                    state = deepcopy(initial)
                    return self.respond(200, state)
            if self.path != '/action':
                return self.respond(404, {'error': {'code': 'not_found'}})
            try:
                count = int(self.headers.get('Content-Length', 0))
                if not 0 < count <= 1048576:
                    raise ValueError('invalid request size')
                action = json.loads(self.rfile.read(count))
                if not isinstance(action, dict):
                    raise ValueError('action must be an object')
                with lock:
                    output = process_portal_event(state, action)
                    if not isinstance(output, dict):
                        raise ValueError('invalid application response')
                    state = output
                    self.respond(400 if 'error' in state else 200, state)
            except Exception:
                self.respond(400, {'error': {'code': 'invalid_action'}})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    server = make_server(args.port)
    print(json.dumps({'port': server.server_port}), flush=True)
    server.serve_forever()
