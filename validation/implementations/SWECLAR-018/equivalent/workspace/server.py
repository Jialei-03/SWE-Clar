"""Loopback HTTP host with isolated SQLite report storage."""
import argparse
import json
import math
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from analysis import analyze
from vision import parse_pgm


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, value, status=200, kind='application/json', download=False):
        data = json.dumps(value, allow_nan=False).encode() if kind == 'application/json' else value.encode()
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="measurement.json"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == '/':
            self.send(Path(__file__).with_name('index.html').read_text(), kind='text/html')
        elif route == '/api/report':
            with sqlite3.connect(self.server.database) as connection:
                row = connection.execute('SELECT document FROM report WHERE singleton=1').fetchone()
            self.send(json.loads(row[0]), download=True) if row else self.send({'error': 'No report'}, 404)
        else:
            self.send({'error': 'Not found'}, 404)

    def do_POST(self):
        try:
            route = urlsplit(self.path).path
            if route not in ('/api/preview', '/api/analyze'):
                return self.send({'error': 'Not found'}, 404)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8000000:
                raise ValueError('Body must be 1..8000000 bytes')
            def reject_constant(value):
                raise ValueError('Non-finite JSON number: ' + value)
            def parse_float(value):
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise ValueError('Non-finite JSON number: ' + value)
                return parsed
            body = json.loads(self.rfile.read(size), parse_constant=reject_constant,
                              parse_float=parse_float)
            if route == '/api/preview':
                if not isinstance(body, dict):
                    raise ValueError('Expected {pgm: string}')
                result = parse_pgm(body.get('pgm'))
            else:
                result = analyze(body)
                with sqlite3.connect(self.server.database) as connection:
                    connection.execute('INSERT OR REPLACE INTO report VALUES (1, ?)', (json.dumps(result, allow_nan=False),))
            self.send(result)
        except (ValueError, UnicodeError, RecursionError) as error:
            self.send({'error': str(error)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default='/tmp/optical.sqlite')
    args = parser.parse_args()
    with sqlite3.connect(args.db) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS report (singleton INTEGER PRIMARY KEY CHECK(singleton=1), document TEXT NOT NULL)')
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.database = args.db
    print(json.dumps({'port': server.server_port}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
