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
_POST_ROUTES = {'/api/curve', '/api/move', '/api/send', '/api/license'}
_JSON_OPTIONS = {'allow_nan': False, 'separators': (',', ':')}


def encode_json(value):
    """Use one compact JSON representation for storage and HTTP responses.

    Whitespace is not part of any public value, so the compact form is an
    equivalent wire/storage encoding while keeping the response boundaries
    small and deterministic.
    """
    return json.dumps(value, **_JSON_OPTIONS)


def state(connection):
    points, revision, next_sequence, acknowledged = connection.execute(
        'SELECT points,revision,next_sequence,acknowledged FROM state'
    ).fetchone()
    points = json.loads(points)
    return {
        'points': points,
        'revision': revision,
        'terminal_angle_degrees': angle(points),
        'next_sequence': next_sequence,
        'last_acknowledged': acknowledged,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        # The application protocol uses stdout for its startup record; do not
        # mix request logs into it.
        pass

    def send(self, value, status=200, kind='application/json'):
        if kind == 'application/json':
            data = encode_json(value).encode('utf-8')
        else:
            data = value.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            index = Path(__file__).with_name('index.html')
            self.send(index.read_text(encoding='utf-8'), kind='text/html')
        elif self.path == '/api/curve':
            with self.server.lock, sqlite3.connect(self.server.database) as connection:
                self.send(state(connection))
        else:
            self.send({'error': 'Not found'}, 404)

    def _read_json_body(self):
        header = self.headers.get('Content-Length')
        try:
            size = int(header) if header is not None else 0
        except (TypeError, ValueError, OverflowError):
            raise ValueError('Expected a JSON body of 1..65536 bytes')
        if not 0 < size <= 65536:
            raise ValueError('Expected a JSON body of 1..65536 bytes')
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError('Expected a complete JSON body')
        try:
            body = json.loads(raw)
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise ValueError('Malformed JSON body') from error
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        return body

    def do_POST(self):
        # Route recognition takes precedence over body validation: an unknown
        # route is always a 404 and cannot mutate state.
        if self.path not in _POST_ROUTES:
            self.send({'error': 'Not found'}, 404)
            return

        try:
            body = self._read_json_body()
            if self.path in ('/api/move', '/api/curve'):
                with self.server.lock, sqlite3.connect(self.server.database) as connection:
                    current = state(connection)
                    if self.path == '/api/curve':
                        points = validate_points(body.get('points'))
                    else:
                        points = move(current['points'], body)
                    if points != current['points']:
                        connection.execute(
                            'UPDATE state SET points=?,revision=revision+1 WHERE singleton=1',
                            (encode_json(points),),
                        )
                    updated = state(connection)
                self.send(updated)
                return

            if self.path == '/api/send':
                positions = body.get('positions')
                if (not isinstance(positions, list) or not 1 <= len(positions) <= 64
                        or not all(valid_number(position) for position in positions)):
                    raise ValueError('Expected 1..64 positions in 0..100')

                # Allocation, the TCP exchange and acknowledgement update are
                # one serialized operation.  This makes sequence observation
                # deterministic even when several HTTP requests arrive at
                # once, while still committing a failed allocation.
                with self.server.lock:
                    with sqlite3.connect(self.server.database) as connection:
                        current = state(connection)
                        sequence = current['next_sequence']
                        connection.execute(
                            'UPDATE state SET next_sequence=next_sequence+1 WHERE singleton=1'
                        )

                    try:
                        response = adapter.send(
                            self.server.driver_port,
                            sequence,
                            current['points'],
                            positions,
                        )
                    except Exception:
                        # The sequence was deliberately consumed above.  Do
                        # not change acknowledged on any protocol or socket
                        # failure.
                        response = None

                    if response is None:
                        failure = {'error': 'driver_failure', 'sequence': sequence}
                    else:
                        with sqlite3.connect(self.server.database) as connection:
                            connection.execute(
                                'UPDATE state SET acknowledged=? WHERE singleton=1',
                                (sequence,),
                            )
                        failure = None

                if failure is not None:
                    self.send(failure, 503)
                else:
                    self.send(response)
                return

            # /api/license
            if not all(isinstance(body.get(name), str) for name in ('uuid', 'product_key')):
                raise ValueError('Expected uuid and product_key strings')
            # The licensing module intentionally returns only a boolean; no
            # fixture data or matching diagnostics cross this boundary.
            self.send({
                'valid': licensing.validate(
                    self.server.licenses, body['uuid'], body['product_key']
                )
            })
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
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
        connection.execute(
            'CREATE TABLE IF NOT EXISTS state ('
            'singleton INTEGER PRIMARY KEY CHECK(singleton=1),'
            'points TEXT NOT NULL, revision INTEGER NOT NULL,'
            'next_sequence INTEGER NOT NULL, acknowledged INTEGER NOT NULL)'
        )
        connection.execute(
            'INSERT OR IGNORE INTO state VALUES (1,?,0,1,0)',
            (encode_json(DEFAULT_POINTS),),
        )

    worker = None
    server = None
    try:
        if args.driver_port is None:
            driver_path = str(Path(__file__).with_name('driver.py'))
            worker = subprocess.Popen(
                [sys.executable, driver_path, '--port', '0'],
                stdout=subprocess.PIPE,
                text=True,
            )
            if worker.stdout is None or not select.select([worker.stdout], [], [], 5)[0]:
                raise RuntimeError('Local driver failed to start')
            args.driver_port = int(json.loads(worker.stdout.readline())['port'])

        server = ThreadingHTTPServer((args.host, args.port), Handler)
        server.daemon_threads = True
        server.database = args.db
        server.driver_port = args.driver_port
        server.licenses = json.loads(Path(args.licenses).read_text(encoding='utf-8'))
        server.lock = threading.Lock()
        print(json.dumps({'port': server.server_port}), flush=True)
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()


if __name__ == '__main__':
    main()
