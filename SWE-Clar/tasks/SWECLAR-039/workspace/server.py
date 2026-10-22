"""Local HTTP dashboard with SQLite workflow persistence and a prepared peer."""
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
from controller import WorkflowError, command, discovery, lifecycle

EMPTY = {'devices':[], 'paired':[], 'connected':None, 'commands':[], 'telemetry':[]}


def read(connection):
    return json.loads(connection.execute('SELECT document FROM state WHERE id=1').fetchone()[0])


def write(connection, state):
    connection.execute('UPDATE state SET document=? WHERE id=1', (json.dumps(state, ensure_ascii=False, allow_nan=False),))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send(self, data, status=200, kind='application/json'):
        data = (json.dumps(data, ensure_ascii=False, allow_nan=False) if kind == 'application/json' else data).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', kind+'; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path == '/': self.send(Path('index.html').read_text(), kind='text/html')
        elif self.path == '/api/state':
            with sqlite3.connect(self.server.database) as connection: self.send(read(connection))
        else: self.send({'error':'not_found'}, 404)
    def do_POST(self):
        if self.path not in ('/api/scan','/api/pair','/api/connect','/api/disconnect','/api/command'):
            return self.send({'error':'not_found'}, 404)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 1 <= size <= 65536: raise ValueError('Body size')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict): raise ValueError('Expected object')
            with self.server.lock:
                with sqlite3.connect(self.server.database) as connection:
                    state = read(connection)
                    op = self.path.removeprefix('/api/')
                    error = None
                    try:
                        if op == 'scan':
                            service = body.get('service')
                            if not isinstance(service, str) or not 1 <= len(service) <= 64:
                                raise WorkflowError('invalid_request', 400)
                            state['devices'] = discovery(self.server.peer_port, service)
                            if state['connected'] not in {d['device_id'] for d in state['devices']}:
                                state['connected'] = None
                            result = state
                        elif op == 'command':
                            result = {'result': command(state, body, self.server.peer_port)}
                        else:
                            lifecycle(state, op, body, self.server.peer_port); result = state
                    except WorkflowError as failure:
                        error = failure
                        if failure.status == 502: state['connected'] = None
                    write(connection, state)
                if error: self.send({'error':error.code}, error.status)
                else: self.send(result)
        except (ValueError, UnicodeError): self.send({'error':'invalid_request'}, 400)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--db',default='/tmp/devices.sqlite');parser.add_argument('--peer-port',type=int);args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
    with sqlite3.connect(args.db) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, document TEXT NOT NULL)')
        connection.execute('INSERT OR IGNORE INTO state VALUES (1,?)',(json.dumps(EMPTY),))
        state=read(connection);state['devices']=[];state['connected']=None;write(connection,state)
    worker=None
    try:
        if args.peer_port is None:
            worker=subprocess.Popen([sys.executable,'peer.py','--port','0','--state',args.db+'.peer.json'],stdout=subprocess.PIPE,text=True)
            if not select.select([worker.stdout],[],[],5)[0]: raise RuntimeError('Synthetic peer did not start')
            args.peer_port=int(json.loads(worker.stdout.readline())['port'])
        server=ThreadingHTTPServer((args.host,args.port),Handler);server.database=args.db;server.peer_port=args.peer_port;server.lock=threading.Lock()
        print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
    finally:
        if worker: worker.terminate();worker.wait(timeout=5)


if __name__=='__main__':main()
