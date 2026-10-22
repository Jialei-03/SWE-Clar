"""Local synthetic service. Request actor IDs are supplied by a trusted caller."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--seed', required=True)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    store = Store(args.db)
    with open(args.seed) as stream:
        store.initialize(json.load(stream))
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value):
            data = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == '/health':
                self.send(200, {'ok': True})
            elif self.path == '/state':
                self.send(200, store.read())
            else:
                self.send(404, {'error': {'code': 'not_found'}})
        def do_POST(self):
            if self.path != '/action':
                return self.send(404, {'error': {'code': 'not_found'}})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size <= 0 or size > 1048576:
                    raise ValueError('invalid size')
                action = json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
                if not isinstance(action, dict):
                    raise ValueError('expected object')
            except (ValueError, UnicodeError):
                return self.send(400, {'error': {'code': 'invalid_request'}})
            self.send(200, store.apply(action))
        def log_message(self, *args):
            pass
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
