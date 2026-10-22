"""Same-origin authenticated marketplace HTTP application."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from store import Failure, Store


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError): pass

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 16384 or self.headers.get('Transfer-Encoding'): raise ValueError('Invalid length')
            raw = self.rfile.read(length)
            if len(raw) != length: raise ValueError('Incomplete body')
            value = json.loads(raw.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid number')))
            if not isinstance(value, dict): raise ValueError('Expected object')
            return value
        except (ValueError, UnicodeDecodeError):
            raise Failure(400, 'invalid_request')

    def dispatch(self):
        method, path = self.command, urlsplit(self.path).path
        store = self.server.store
        try:
            if (method, path) == ('GET', '/health'): return self.reply(200, {'ok': True})
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if method == 'GET' and path in static:
                name, mime = static[path]
                return self.reply(200, Path(__file__).with_name(name).read_bytes(), mime)
            if (method, path) == ('POST', '/api/login'): return self.reply(200, store.login(self.body()))
            detail = re.fullmatch('/api/listings/([^/]+)', path) if method == 'GET' else None
            listing_action = re.fullmatch('/api/listings/([^/]+)/(questions|offers)', path) if method == 'POST' else None
            price = re.fullmatch('/api/listings/([^/]+)/price', path) if method == 'PATCH' else None
            offer_action = re.fullmatch('/api/offers/([^/]+)/(counter|accept)', path) if method == 'POST' else None
            fixed = (method, path) in {('POST', '/api/logout'), ('GET', '/api/catalog'), ('GET', '/api/agreements')}
            if not (fixed or detail or listing_action or price or offer_action): raise Failure(404, 'not_found')
            authorization = self.headers.get('Authorization', '')
            user = store.actor(authorization)
            if detail: return self.reply(200, store.detail(user, unquote(detail[1])))
            if (method, path) == ('GET', '/api/catalog'): return self.reply(200, store.catalog(user))
            if (method, path) == ('GET', '/api/agreements'): return self.reply(200, store.agreements(user))
            body = self.body()
            if path == '/api/logout': return self.reply(200, store.logout(authorization))
            if listing_action:
                handler = store.questions if listing_action[2] == 'questions' else store.place_offer
                return self.reply(201, handler(user, unquote(listing_action[1]), body))
            if price: return self.reply(200, store.change_price(user, unquote(price[1]), body))
            handler = store.counter if offer_action[2] == 'counter' else store.accept
            return self.reply(200, handler(user, unquote(offer_action[1]), body))
        except Failure as error:
            self.reply(error.status, {'error': error.code})

    do_GET = dispatch
    do_POST = dispatch
    do_PATCH = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch
    do_OPTIONS = dispatch
    do_HEAD = dispatch

    def log_message(self, *_): pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', required=True)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--clock', required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db, args.fixture, args.clock)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
