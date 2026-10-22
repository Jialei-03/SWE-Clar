from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import sqlite3
from urllib.parse import parse_qs, urlsplit

from store import Store


ROOT = Path(__file__).parent
store = Store(
    os.environ['DATABASE_PATH'],
    json.loads(Path(os.environ['IDENTITIES_PATH']).read_text()),
)
MAX_BODY = 16_000_000


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # Diagnostics are intentionally not written into HTTP responses.
        pass

    def reply(self, status, mime, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def token(self):
        header = self.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            raise PermissionError('unauthorized')
        token = header[7:]
        store.identity(token)
        return token

    def do_GET(self):
        url = urlsplit(self.path)
        static = {
            '/': ('index.html', 'text/html'),
            '/app.js': ('app.js', 'text/javascript'),
            '/style.css': ('style.css', 'text/css'),
        }
        if url.path in static:
            filename, mime = static[url.path]
            # Only the explicit public assets above are ever opened.  In
            # particular, configuration, source, and database files are not
            # part of a generic static-file route.
            return self.reply(200, mime, (ROOT / filename).read_bytes())

        try:
            token = self.token()
            if url.path == '/staff':
                return self.reply(
                    200,
                    'application/json',
                    json.dumps(store.list_staff(token)).encode('utf-8'),
                )
            if url.path == '/history':
                return self.reply(
                    200,
                    'application/json',
                    json.dumps(store.history(token)).encode('utf-8'),
                )
            if url.path == '/export.csv':
                return self.reply(200, 'text/csv', store.export(token))
            if url.path == '/photo':
                ident = parse_qs(url.query, keep_blank_values=True).get('id', [''])[0]
                return self.reply(200, 'image/png', store.photo(token, ident))
            self.reply(404, 'text/plain', b'Not found')
        except PermissionError:
            self.reply(403, 'application/json', b'{"error":"forbidden"}')
        except Exception:
            self.reply(400, 'application/json', b'{"error":"invalid_request"}')

    def do_POST(self):
        if urlsplit(self.path).path != '/action':
            return self.reply(404, 'text/plain', b'Not found')
        try:
            token = self.token()
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= MAX_BODY:
                raise ValueError('invalid_request')
            payload = self.rfile.read(length)
            result = store.action(token, json.loads(payload))
            self.reply(
                200,
                'application/json',
                json.dumps(result).encode('utf-8'),
            )
        except PermissionError:
            self.reply(403, 'application/json', b'{"error":"forbidden"}')
        except sqlite3.IntegrityError:
            self.reply(409, 'application/json', b'{"error":"conflict"}')
        except Exception:
            self.reply(400, 'application/json', b'{"error":"invalid_request"}')


http = ThreadingHTTPServer(
    ('127.0.0.1', int(os.environ.get('PORT', '0'))),
    Handler,
)
print(json.dumps({'port': http.server_port}), flush=True)
http.serve_forever()
