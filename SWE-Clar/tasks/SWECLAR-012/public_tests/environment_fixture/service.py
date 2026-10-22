"""Independent HTTP/SQLite environment fixture; no task business implementation."""
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

p = argparse.ArgumentParser()
p.add_argument('--db', required=True)
p.add_argument('--port', type=int, required=True)
a = p.parse_args()
with sqlite3.connect(a.db) as db:
    db.execute('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, body TEXT NOT NULL)')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != '/notes':
            return self.reply(404, {'error': 'not_found'})
        with sqlite3.connect(a.db) as db:
            rows = db.execute('SELECT id,body FROM notes ORDER BY id').fetchall()
        self.reply(200, {'notes': [{'id': r[0], 'body': r[1]} for r in rows]})

    def do_POST(self):
        if self.path != '/notes':
            return self.reply(404, {'error': 'not_found'})
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with sqlite3.connect(a.db) as db:
            cursor = db.execute('INSERT INTO notes(body) VALUES(?)', (data['body'],))
        self.reply(201, {'id': cursor.lastrowid, 'body': data['body']})


ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()
