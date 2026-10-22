"""Independent synthetic property-workspace application."""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from domain import AppError, analysis
from integration import Integration
from store import Store

ROOT = Path(__file__).resolve().parent


def serve(args):
    if not args.offer_service:
        raise ValueError('Prepared loopback offer-service URL required')
    store = Store(args.db, json.loads(Path(args.seed).read_text()))
    peer = urlsplit(args.offer_service)
    if (
        peer.scheme != 'http'
        or peer.hostname != '127.0.0.1'
        or not peer.port
        or peer.path not in ['', '/']
        or peer.query
        or peer.fragment
    ):
        raise ValueError('Prepared loopback offer-service URL required')
    integration = Integration(store, args.offer_service.rstrip('/'))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def read_body(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError('body size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('object body required')
                return body
            except (ValueError, TypeError, UnicodeDecodeError):
                raise AppError(400, {'body': 'JSON object required'})

        def dispatch(self):
            path = urlsplit(self.path).path
            if self.command == 'GET' and path in ['/', '/app.js', '/style.css']:
                filename = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
                mime = {'/': 'text/html', '/app.js': 'application/javascript', '/style.css': 'text/css'}[path]
                return 200, (ROOT / filename).read_bytes(), mime
            if self.command == 'GET' and path == '/health':
                return 200, {'ready': True}, None
            if self.command == 'GET' and path == '/api/actors':
                return 200, {'actors': store.actors()}, None

            # These are infrastructure simulation paths.  They deliberately
            # do not consume or infer an application actor identity.
            if self.command == 'POST' and path == '/api/offer-events':
                body = self.read_body()
                return 200, integration.receive(body.get('events')), None
            if self.command == 'POST' and path == '/api/sync':
                body = self.read_body()
                callback = f'http://127.0.0.1:{self.server.server_port}/api/offer-events'
                return 200, integration.sync(body.get('now'), callback), None

            # Authenticate user routes before validating their request body.
            # This keeps an unknown upstream identity from learning anything
            # about route or field validation.
            actor = store.actor(self.headers.get('X-Actor'))
            body = {}
            if self.command in ['POST', 'PUT']:
                body = self.read_body()

            parts = path.strip('/').split('/')
            if path == '/api/listings':
                if self.command == 'GET':
                    return 200, {'listings': store.listings(actor)}, None
                if self.command == 'POST':
                    return 201, {'listing': store.save(actor, body)}, None

            if len(parts) in [3, 4] and parts[:2] == ['api', 'listings']:
                key = unquote(parts[2])
                if len(parts) == 3 and self.command == 'GET':
                    return 200, store.get(actor, key), None
                if len(parts) == 3 and self.command == 'PUT':
                    return 200, {'listing': store.save(actor, body, key)}, None
                if len(parts) == 4 and parts[3] == 'analysis' and self.command == 'POST':
                    return 200, analysis(store.get(actor, key)['listing'], body), None

            if (
                len(parts) == 4
                and parts[:2] == ['api', 'offers']
                and parts[3] == 'review'
                and self.command == 'POST'
            ):
                return 200, {'url': store.review(actor, unquote(parts[2]), integration.service_url)}, None
            raise AppError(404, {'route': 'not found'})

        def handle_request(self):
            try:
                status, value, mime = self.dispatch()
            except AppError as error:
                status, value, mime = error.status, {'errors': error.errors}, None
            except Exception:
                # Keep unexpected internal details (including filesystem
                # paths) out of the public response.
                status, value, mime = 500, {'errors': {'server': 'internal error'}}, None
            data = value if mime else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', (mime or 'application/json') + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        do_GET = handle_request
        do_POST = handle_request
        do_PUT = handle_request

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(json.dumps({'port': server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--db', required=True)
    parser.add_argument('--seed', default=str(ROOT / 'seed.json'))
    parser.add_argument('--offer-service', default=os.environ.get('OFFER_SERVICE_URL'))
    serve(parser.parse_args())
