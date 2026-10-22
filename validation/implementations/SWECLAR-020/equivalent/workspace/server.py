"""HTTP attendance application; the reader endpoint is configured by the benchmark."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from store import Store, Failure, text
from reader import fetch_reading


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status); self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError): pass

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 65536 or self.headers.get('Transfer-Encoding'): raise ValueError()
            raw = self.rfile.read(length)
            if len(raw) != length: raise ValueError()
            value = json.loads(raw.decode(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict): raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError): raise Failure(400, 'invalid_request')

    def dispatch(self):
        method, path, store = self.command, urlsplit(self.path).path, self.server.store
        try:
            if (method, path) == ('GET', '/health'): return self.reply(200, {'ok': True})
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if method == 'GET' and path in static:
                file, mime = static[path]; return self.reply(200, Path(__file__).with_name(file).read_bytes(), mime)
            if (method, path) == ('POST', '/api/login'): return self.reply(200, store.login(self.body()))
            fixed = {('POST', '/api/logout'), ('GET', '/api/me'), ('GET', '/api/roster'), ('GET', '/api/scans'), ('POST', '/api/scans'), ('GET', '/api/attendance'), ('GET', '/api/inbox')}
            item = re.fullmatch('/api/(tags|guardians|inbox)/([^/]+)', path)
            confirm = re.fullmatch('/api/scans/([^/]+)/confirm', path)
            valid = (method, path) in fixed or (item and ((method == 'PATCH' and item[1] in ['tags', 'guardians']) or (method == 'PUT' and item[1] == 'inbox'))) or (confirm and method == 'POST')
            if not valid: raise Failure(404, 'not_found')
            authorization = self.headers.get('Authorization', ''); user = store.actor(authorization)
            if method == 'GET':
                if path == '/api/me': return self.reply(200, {'user': store.public_user(user)})
                handler = {'/api/roster': store.roster, '/api/scans': store.scans, '/api/attendance': store.attendance, '/api/inbox': store.inbox}[path]
                return self.reply(200, handler(user))
            # Role checks precede request syntax and resource lookup for all
            # role-restricted mutation routes.  This keeps a parent from
            # probing staff resources with malformed requests, and keeps an
            # ordinary user from probing administrative IDs.
            if path == '/api/logout':
                self.body()  # logout accepts an object; unknown fields are ignored
                return self.reply(200, store.logout(authorization))
            if item:
                if item[1] == 'inbox':
                    if user['role'] != 'parent': raise Failure(403, 'forbidden')
                else:
                    if user['role'] != 'administrator': raise Failure(403, 'forbidden')
                body = self.body()
                key = unquote(item[2])
                value = store.set_read(user, key, body) if item[1] == 'inbox' else store.set_active(user, item[1], key, body)
                return self.reply(200, value)
            if confirm:
                store.staff(user)
                body = self.body()
                status, value = store.confirm(user, unquote(confirm[1]), body); return self.reply(status, value)
            store.staff(user)
            body = self.body()
            key = text(body.get('reading_id'))
            direction = body.get('direction')
            if direction not in ['in', 'out']: raise Failure(400, 'invalid_request')
            reading = fetch_reading(self.server.reader, key)
            status, value = store.scan(user, reading, direction); return self.reply(status, value)
        except Failure as error: self.reply(error.status, {'error': {'code': error.code}})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = dispatch
    def log_message(self, *_): pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--host', default='0.0.0.0'); parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', required=True); parser.add_argument('--fixture', required=True); parser.add_argument('--reader', required=True)
    args = parser.parse_args(); server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db, args.fixture); server.reader = args.reader
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
