"""Curve editor HTTP host, SQLite persistence and local driver integration."""
import argparse
import json
import select
import signal
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import adapter
import licensing
from geometry import angle, move, validate_points, valid_number

DEFAULT_POINTS = [{'x': 0, 'y': 0}, {'x': 40, 'y': 30}, {'x': 80, 'y': 30}]


def state(connection):
    points, revision, next_sequence, acknowledged = connection.execute('SELECT points,revision,next_sequence,acknowledged FROM state').fetchone()
    points = json.loads(points)
    return {'points': points, 'revision': revision, 'terminal_angle_degrees': angle(points),
            'next_sequence': next_sequence, 'last_acknowledged': acknowledged}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, value, status=200, kind='application/json'):
        data = json.dumps(value, allow_nan=False).encode() if kind == 'application/json' else value.encode()
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            self.send(Path('index.html').read_text(), kind='text/html')
        elif self.path == '/api/curve':
            with sqlite3.connect(self.server.database) as connection:
                self.send(state(connection))
        else:
            self.send({'error': 'Not found'}, 404)

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                raise ValueError('Expected a JSON body of 1..65536 bytes')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            if self.path in ('/api/move', '/api/curve'):
                with self.server.lock, sqlite3.connect(self.server.database) as connection:
                    current = state(connection)
                    points = (validate_points(body.get('points')) if self.path == '/api/curve'
                              else move(current['points'], body))
                    if points != current['points']:
                        connection.execute('UPDATE state SET points=?,revision=revision+1', (json.dumps(points),))
                    updated = state(connection)
                self.send(updated)
            elif self.path == '/api/send':
                positions = body.get('positions')
                if not isinstance(positions, list) or not 1 <= len(positions) <= 64 or not all(valid_number(x) for x in positions):
                    raise ValueError('Expected 1..64 positions in 0..100')
                with self.server.lock:
                    with sqlite3.connect(self.server.database) as connection:
                        current = state(connection)
                        sequence = current['next_sequence']
                        connection.execute('UPDATE state SET next_sequence=next_sequence+1')
                    try:
                        response = adapter.send(self.server.driver_port, sequence, current['points'], positions)
                    except (OSError, ValueError, UnicodeError) as error:
                        return self.send({'error': 'driver_failure', 'sequence': sequence}, 503)
                    with sqlite3.connect(self.server.database) as connection:
                        connection.execute('UPDATE state SET acknowledged=?', (sequence,))
                    self.send(response)
            elif self.path == '/api/license':
                if not all(isinstance(body.get(k), str) for k in ('uuid', 'product_key')):
                    raise ValueError('Expected uuid and product_key strings')
                self.send({'valid': licensing.validate(self.server.licenses, body['uuid'], body['product_key'])})
            else:
                self.send({'error': 'Not found'}, 404)
        except (ValueError, UnicodeError) as error:
            self.send({'error': str(error)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default='/tmp/curves.sqlite')
    parser.add_argument('--driver-port', type=int)
    parser.add_argument('--licenses', default='licenses.json')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with sqlite3.connect(args.db) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS state (singleton INTEGER PRIMARY KEY CHECK(singleton=1),points TEXT NOT NULL,revision INTEGER NOT NULL,next_sequence INTEGER NOT NULL,acknowledged INTEGER NOT NULL)')
        connection.execute('INSERT OR IGNORE INTO state VALUES (1,?,0,1,0)', (json.dumps(DEFAULT_POINTS),))
    worker = None
    try:
        if args.driver_port is None:
            worker = subprocess.Popen([sys.executable, 'driver.py', '--port', '0'], stdout=subprocess.PIPE, text=True)
            if not select.select([worker.stdout], [], [], 5)[0]:
                raise RuntimeError('Local driver failed to start')
            args.driver_port = int(json.loads(worker.stdout.readline())['port'])
        server = ThreadingHTTPServer((args.host, args.port), Handler)
        server.database, server.driver_port = args.db, args.driver_port
        server.licenses = json.loads(Path(args.licenses).read_text())
        server.lock = threading.Lock()
        print(json.dumps({'port': server.server_port}), flush=True)
        server.serve_forever()
    finally:
        if worker:
            worker.terminate()
            worker.wait(timeout=5)


if __name__ == '__main__':
    main()
