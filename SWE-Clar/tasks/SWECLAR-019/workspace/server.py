"""Same-origin authenticated route workspace HTTP server."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit
from store import Failure, Store


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
            if not 1 <= length <= 800000 or self.headers.get('Transfer-Encoding'): raise ValueError('Invalid length')
            raw = self.rfile.read(length)
            if len(raw) != length: raise ValueError('Incomplete body')
            value = json.loads(raw.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid number')))
            if not isinstance(value, dict): raise ValueError('Expected object')
            return value
        except (ValueError, UnicodeDecodeError): raise Failure(400, 'invalid_request')

    def dispatch(self):
        method = self.command; url = urlsplit(self.path); path = url.path; store = self.server.store
        try:
            if (method, path) == ('GET', '/health'): return self.reply(200, {'ok': True})
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if method == 'GET' and path in static:
                name, mime = static[path]; return self.reply(200, Path(__file__).with_name(name).read_bytes(), mime)
            if (method, path) == ('POST', '/api/login'): return self.reply(200, store.login(self.body()))
            fixed = {('POST', '/api/logout'), ('GET', '/api/me'), ('GET', '/api/assets'), ('POST', '/api/assets'),
                     ('PUT', '/api/profile'), ('GET', '/api/waypoints'), ('POST', '/api/waypoints'),
                     ('GET', '/api/routes'), ('POST', '/api/routes'), ('PUT', '/api/touring-status')}
            item = re.fullmatch('/api/(assets|waypoints|routes)/([^/]+)', path)
            action = re.fullmatch('/api/(waypoints|routes)/([^/]+)/(comments|pin)', path)
            valid_item = item and (method == 'GET' or (method == 'PATCH' and item[1] == 'waypoints'))
            valid_action = action and ((method, action[1], action[3]) in {('POST', 'waypoints', 'comments'), ('PUT', 'routes', 'pin')})
            if (method, path) not in fixed and not valid_item and not valid_action: raise Failure(404, 'not_found')
            authorization = self.headers.get('Authorization', ''); actor = store.actor(authorization)
            if method == 'GET':
                if item:
                    key = unquote(item[2])
                    if item[1] == 'assets': return self.reply(200, store.asset(actor, key), 'image/png')
                    return self.reply(200, (store.waypoint if item[1] == 'waypoints' else store.route)(actor, key))
                if path == '/api/routes':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.reply(200, store.routes(actor, query.get('sort', ['asc'])[0], query.get('q', [''])[0]))
                return self.reply(200, {'/api/me': store.me, '/api/assets': store.assets, '/api/waypoints': store.waypoints}[path](actor))
            body = self.body()
            if path == '/api/logout': return self.reply(200, store.logout(authorization))
            if item: return self.reply(200, store.edit_waypoint(actor, unquote(item[2]), body))
            if action:
                if action[3] == 'comments':
                    status, value = store.comment(actor, unquote(action[2]), body); return self.reply(status, value)
                return self.reply(200, store.pin(actor, unquote(action[2]), body))
            handlers = {'/api/assets': (201, store.upload), '/api/profile': (200, store.save_profile),
                        '/api/waypoints': (201, store.create_waypoint), '/api/routes': (201, store.create_route), '/api/touring-status': (200, store.status)}
            status, handler = handlers[path]; return self.reply(status, handler(actor, body))
        except Failure as error: self.reply(error.status, {'error': error.code})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = dispatch
    def log_message(self, *_): pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--host', default='0.0.0.0'); parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', required=True); parser.add_argument('--fixture', required=True); args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler); server.store = Store(args.db, args.fixture)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
