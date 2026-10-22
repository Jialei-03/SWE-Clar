"""Stateless local HTTP transport for the independent lattice explorer."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
from engine import geometry

ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, kind='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send(200, {'ok': True})
        assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if path in assets:
            name, kind = assets[path]
            return self.send(200, (ROOT / name).read_bytes(), kind + '; charset=utf-8')
        self.send(404, {'error': 'not_found'})

    def do_POST(self):
        if urlsplit(self.path).path != '/api/geometry':
            return self.send(404, {'error': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 8192:
                raise ValueError('Invalid length')
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            result = geometry(body)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError,
                OverflowError, RecursionError):
            return self.send(400, {'error': 'invalid_request'})
        self.send(200, result)

    def unsupported(self):
        self.send(404, {'error': 'not_found'})

    # Explicitly handle the common methods.  BaseHTTPRequestHandler uses 501
    # for an unknown method; that is also mapped to the public 404 contract by
    # send_error below.
    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = unsupported
    do_TRACE = do_CONNECT = do_PRI = unsupported

    def send_error(self, code, message=None, explain=None):
        if code == 501:
            return self.send(404, {'error': 'not_found'})
        return super().send_error(code, message, explain)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
