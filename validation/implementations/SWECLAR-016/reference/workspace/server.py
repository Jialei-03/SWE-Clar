"""Same-origin browser application with authenticated JSON and image endpoints."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re

from provider import Provider
from store import Failure, Store


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            limit = 1048576 if self.path == '/api/assets' else 16384
            if not 1 <= size <= limit or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid body size')
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError('Incomplete body')
            value = json.loads(raw.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid number')))
            if not isinstance(value, dict):
                raise ValueError('Expected object')
            return value
        except (ValueError, UnicodeDecodeError, RecursionError, OverflowError):
            raise Failure(400, 'invalid_request')

    def dispatch(self):
        method, path, store = self.command, self.path, self.server.store
        try:
            if (method, path) == ('GET', '/health'):
                return self.reply(200, {'ok': True})
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if method == 'GET' and path in static:
                filename, mime = static[path]
                return self.reply(200, Path(__file__).with_name(filename).read_bytes(), mime)
            if (method, path) == ('POST', '/api/login'):
                return self.reply(200, store.login(self.body()))
            fixed = {
                ('GET', '/api/workspace'), ('POST', '/api/logout'),
                ('POST', '/api/conversations'), ('POST', '/api/assets'),
                ('POST', '/api/extract'), ('POST', '/api/coach'), ('POST', '/api/rank'),
                ('PUT', '/api/profile'), ('GET', '/api/rankings')}
            conversation = re.fullmatch(r'/api/conversations/([^/]+)', path) if method == 'GET' else None
            image = re.fullmatch(r'/api/assets/([^/]+)/image', path) if method == 'GET' else None
            if (method, path) not in fixed and not conversation and not image:
                raise Failure(404, 'not_found')
            authorization = self.headers.get('Authorization', '')
            owner = store.actor(authorization)
            if conversation:
                return self.reply(200, store.conversation(owner, conversation[1]))
            if image:
                return self.reply(200, store.image(owner, image[1]), 'image/png')
            if method == 'GET':
                return self.reply(200, store.workspace(owner) if path == '/api/workspace' else store.rankings(owner))
            body = self.body()
            if path == '/api/logout':
                return self.reply(200, store.logout(authorization))
            if path == '/api/conversations':
                return self.reply(201, store.create_conversation(owner, body))
            if path == '/api/assets':
                return self.reply(201, store.upload(owner, body))
            if path == '/api/profile':
                return self.reply(200, store.save_profile(owner, body))
            return self.reply(200, store.workflow(owner, path.rsplit('/', 1)[1], body))
        except Failure as failure:
            self.reply(failure.status, {'error': failure.code})

    do_GET = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch
    do_PATCH = dispatch
    do_OPTIONS = dispatch
    do_HEAD = dispatch
    do_TRACE = dispatch
    do_CONNECT = dispatch

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler otherwise emits HTML/501 for an uncommon
        # method before dispatch can apply the public JSON 404 contract.
        if code == 501:
            return self.reply(404, {'error': 'not_found'})
        return super().send_error(code, message, explain)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', required=True)
    parser.add_argument('--uploads', required=True)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--provider-token', required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db, args.uploads, args.fixture, Provider(args.provider, args.provider_token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
