import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from model import Rejected, apply, host, initial

ROOT = Path(__file__).resolve().parent


def database(path):
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.execute('CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
    connection.execute('INSERT OR IGNORE INTO workspace VALUES (1, ?)', (json.dumps(initial()),))
    return connection


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def send(self, status, body, kind='application/json'):
        encoded = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', kind+'; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded))); self.end_headers(); self.wfile.write(encoded)

    def do_GET(self):
        if self.path in ('/api/state', '/api/document'):
            with database(self.server.db) as connection:
                data = json.loads(connection.execute('SELECT payload FROM workspace WHERE id=1').fetchone()[0])
            return self.send(200, data['state'] if self.path == '/api/state' else {'nodes': data['document'], 'current': data['current']})
        static = {'/': ('index.html', 'text/html'), '/host.js': ('host.js', 'text/javascript'),
                  '/sidebar.js': ('sidebar.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css')}
        if self.path not in static: return self.send(404, {'error': 'not_found'})
        name, kind = static[self.path]; self.send(200, (ROOT/name).read_text(), kind)

    def do_POST(self):
        if self.path not in ('/api/action', '/api/host'): return self.send(404, {'error': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536: raise Rejected('invalid_command')
            command = json.loads(self.rfile.read(length))
            connection = database(self.server.db)
            try:
                connection.execute('BEGIN IMMEDIATE')
                before = json.loads(connection.execute('SELECT payload FROM workspace WHERE id=1').fetchone()[0])
                after = (apply if self.path == '/api/action' else host)(before, command)
                connection.execute('UPDATE workspace SET payload=? WHERE id=1', (json.dumps(after),))
                connection.commit()
            except BaseException:
                connection.rollback(); raise
            finally: connection.close()
            self.send(200, after['state'] if self.path == '/api/action' else {'nodes': after['document'], 'current': after['current']})
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            self.send(400, {'error': str(error) if isinstance(error, Rejected) else 'invalid_command'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8000); parser.add_argument('--db', default='workspace.sqlite')
    args = parser.parse_args(); connection = database(args.db); connection.close()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler); server.db = args.db
    print(json.dumps({'port': server.server_port}), flush=True); server.serve_forever()
