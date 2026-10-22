"""Standalone local HTTP entry point for the synthetic arena."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
from arena import Arena, Conflict, reject

ROOT = Path(__file__).resolve().parent


def handler(arena):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, content_type='application/json'):
            data = json.dumps(value, ensure_ascii=False).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, method):
            try:
                path = urlsplit(self.path).path
                if method == 'GET' and path in ('/', '/app.js', '/style.css'):
                    name = 'index.html' if path == '/' else path[1:]
                    mime = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
                    return self.send(200, (ROOT / name).read_bytes(), mime)
                if method == 'GET' and path == '/health':
                    return self.send(200, {'ok': True})
                if method == 'GET' and path == '/api/rooms':
                    return self.send(200, arena.catalog())
                body = {}
                if method == 'POST':
                    try:
                        length = int(self.headers.get('Content-Length', ''))
                        if not 0 < length <= 16384:
                            raise ValueError()
                        body = json.loads(self.rfile.read(length))
                        if not isinstance(body, dict):
                            raise ValueError()
                    except (ValueError, UnicodeDecodeError):
                        reject(400, 'invalid_request')
                if method == 'POST' and path == '/api/join':
                    return self.send(201, arena.join(body))
                auth = self.headers.get('Authorization', '')
                token = auth[7:] if auth.startswith('Bearer ') else None
                if method == 'GET' and path == '/api/state':
                    return self.send(200, arena.state(token))
                if method == 'POST' and path == '/api/leave':
                    return self.send(200, arena.leave(token))
                if method == 'POST' and path in ('/api/move', '/api/respawn'):
                    return self.send(200, arena.command(token, path.rsplit('/', 1)[1], body))
                reject(404, 'not_found')
            except Conflict as exc:
                self.send(exc.status, {'error': exc.code})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {'error': 'service_error'})

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')

        def do_PUT(self):
            self.send(404, {'error': 'not_found'})

        do_DELETE = do_PATCH = do_PUT
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--world', default='fixtures/world.json')
    parser.add_argument('--clock-file', default='fixtures/clock.json')
    args = parser.parse_args()
    arena = Arena(json.loads(Path(args.world).read_text()), args.clock_file)
    ThreadingHTTPServer((args.host, args.port), handler(arena)).serve_forever()
