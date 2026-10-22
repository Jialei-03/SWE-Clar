"""Local HTTP entry point for the independently constructed appointment app."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from store import Rejected, Store, reject


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def reply(self, status, value):
            # ASCII escaping keeps every JSON response UTF-8 encodable even
            # when a user-supplied display string contains a lone surrogate.
            data = json.dumps(value, ensure_ascii=True).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A committed transaction can legitimately lose its reply.

        def body(self):
            length = self.headers.get('Content-Length')
            if (self.headers.get('Transfer-Encoding') or length is None or
                    not length or any(char not in '0123456789' for char in length)):
                reject(400, 'invalid_request')
            length = int(length)
            if length < 1 or length > 32768:
                reject(400, 'invalid_request')
            try:
                def reject_constant(_):
                    raise ValueError('non-standard JSON number')
                value = json.loads(
                    self.rfile.read(length).decode('utf-8'),
                    parse_constant=reject_constant,
                )
            except (ValueError, UnicodeError):
                reject(400, 'invalid_request')
            if not isinstance(value, dict):
                reject(400, 'invalid_request')
            return value

        def dispatch(self, method):
            try:
                url = urlsplit(self.path)
                path = unquote(url.path)
                if method == 'GET' and path == '/health':
                    return self.reply(200, {'ok': True})
                body = self.body() if method == 'POST' else {}
                if method == 'POST' and path == '/api/login':
                    return self.reply(200, store.login(body))
                authorization = self.headers.get('Authorization', '')
                token = authorization[7:] if authorization.startswith('Bearer ') else ''
                actor = store.actor(token)
                if method == 'POST' and path == '/api/logout':
                    result = store.logout(token)
                elif method == 'GET' and path == '/api/me':
                    result = {'user': actor}
                elif method == 'GET' and path == '/api/catalog':
                    result = store.catalog()
                elif method == 'GET' and path == '/api/slots':
                    query = parse_qs(url.query, keep_blank_values=True)
                    if any(len(v) != 1 for v in query.values()):
                        reject(400, 'invalid_request')
                    result = store.availability({key: values[0] for key, values in query.items()})
                elif method == 'POST' and path == '/api/slots':
                    return self.reply(201, store.publish(actor, body))
                elif method == 'POST' and path == '/api/book':
                    status, result = store.book(actor, body)
                    return self.reply(status, result)
                elif method == 'GET' and path == '/api/appointments':
                    result = store.appointments(actor)
                else:
                    parts = path.strip('/').split('/')
                    if len(parts) not in (3, 4) or parts[:2] != ['api', 'appointments'] or not parts[2]:
                        reject(404, 'not_found')
                    appointment_id = parts[2]
                    if method == 'GET' and len(parts) == 3:
                        result = store.appointment(actor, appointment_id)
                    elif method == 'POST' and len(parts) == 4 and parts[3] == 'cancel':
                        result = store.cancel(actor, appointment_id, body)
                    elif method == 'POST' and len(parts) == 4 and parts[3] == 'move':
                        result = store.move(actor, appointment_id, body)
                    else:
                        reject(404, 'not_found')
                self.reply(200, result)
            except Rejected as exc:
                self.reply(exc.status, {'error': exc.code})
            except sqlite3.Error:
                self.reply(500, {'error': 'storage_error'})

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')

        # Keep unsupported verbs in the JSON wire contract instead of letting
        # BaseHTTPRequestHandler emit an HTML 501 page.
        def do_PUT(self):
            self.reply(404, {'error': 'not_found'})

        def do_PATCH(self):
            self.reply(404, {'error': 'not_found'})

        def do_DELETE(self):
            self.reply(404, {'error': 'not_found'})

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', default='fixtures/clinic.json')
    p.add_argument('--db', default='/tmp/clinic/store.sqlite')
    p.add_argument('--clock-file', default='fixtures/clock.json')
    p.add_argument('--port', type=int, default=8081)
    args = p.parse_args()
    store = Store(args.db, args.fixture, args.clock_file)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(store))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
