"""Benchmark-owned synthetic tag reader. This is not an NFC hardware driver."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from urllib.parse import unquote, urlsplit


class Reader:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row; self.lock = threading.RLock()
        self.db.executescript('CREATE TABLE IF NOT EXISTS readings(id TEXT PRIMARY KEY,record TEXT NOT NULL); CREATE TABLE IF NOT EXISTS requests(method TEXT,path TEXT);')

    def request(self, method, path, value):
        with self.lock:
            self.db.execute('INSERT INTO requests VALUES(?,?)', (method, path))
            if method == 'GET' and path == '/health': return 200, {'ok': True}
            if method == 'POST' and path == '/readings':
                valid = isinstance(value, dict) and all(isinstance(value.get(k), str) and 1 <= len(value[k]) <= 100 for k in ['uid', 'device_id'])
                valid = valid and value.get('interaction') in ['tap', 'proximity'] and type(value.get('at')) is int and 0 <= value['at'] <= 2000000000
                if not valid: return 400, {'error': {'code': 'invalid_request'}}
                reading = {k: value[k] for k in ['uid', 'device_id', 'interaction', 'at']}; reading['id'] = secrets.token_urlsafe(24)
                self.db.execute('INSERT INTO readings VALUES(?,?)', (reading['id'], json.dumps(reading)))
                return 201, {'reading': reading}
            if method == 'GET' and path.startswith('/readings/'):
                row = self.db.execute('SELECT record FROM readings WHERE id=?', (unquote(path[len('/readings/'):]),)).fetchone()
                if row: return 200, {'reading': json.loads(row[0])}
            return 404, {'error': {'code': 'not_found'}}


class Handler(BaseHTTPRequestHandler):
    def dispatch(self):
        if self.command == 'OPTIONS': status, value = 200, {'ok': True}
        else:
            try:
                value = None
                if self.command == 'POST':
                    n = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= n <= 65536 or self.headers.get('Transfer-Encoding'): raise ValueError()
                    raw = self.rfile.read(n)
                    if len(raw) != n: raise ValueError()
                    value = json.loads(raw.decode(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                status, value = self.server.reader.request(self.command, urlsplit(self.path).path, value)
            except (ValueError, UnicodeDecodeError): status, value = 400, {'error': {'code': 'invalid_request'}}
        raw = json.dumps(value).encode(); self.send_response(status)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
        self.send_header('Access-Control-Allow-Origin', '*'); self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type'); self.send_header('Cache-Control', 'no-store'); self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError): pass

    do_GET = do_POST = do_OPTIONS = dispatch
    def log_message(self, *_): pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8081); parser.add_argument('--db', required=True)
    args = parser.parse_args(); Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler); server.reader = Reader(args.db)
    print(json.dumps({'port': server.server_address[1]}), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
