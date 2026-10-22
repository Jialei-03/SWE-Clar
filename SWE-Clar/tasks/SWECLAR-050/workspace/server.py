import argparse
import json
import sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from workshop import initial,apply,Rejected

ROOT=Path(__file__).resolve().parent


def connection(path):return sqlite3.connect(path,timeout=10,isolation_level=None)
def initialize(path):
    with connection(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS workshop(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO workshop VALUES(1,?)',(json.dumps(initial()),))


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def send(self,status,body,kind='application/json'):
        if not isinstance(body,bytes):body=json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/api/state':
            db=connection(self.server.db)
            try:self.send(200,json.loads(db.execute('SELECT payload FROM workshop WHERE id=1').fetchone()[0]))
            finally:db.close()
            return
        files={'/':('index.html','text/html; charset=utf-8'),'/render.js':('render.js','text/javascript'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path not in files:return self.send(404,{'error':'not_found'})
        name,kind=files[self.path];self.send(200,(ROOT/name).read_bytes(),kind)
    def do_POST(self):
        if self.path!='/api/command':return self.send(404,{'error':'not_found'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=65536:raise Rejected('invalid_command')
            value=json.loads(self.rfile.read(size));db=connection(self.server.db)
            try:
                db.execute('BEGIN IMMEDIATE');before=json.loads(db.execute('SELECT payload FROM workshop WHERE id=1').fetchone()[0]);after=apply(before,value)
                db.execute('UPDATE workshop SET payload=? WHERE id=1',(json.dumps(after),));db.commit()
            except BaseException:db.rollback();raise
            finally:db.close()
            self.send(200,after)
        except (ValueError,KeyError,TypeError) as error:self.send(400,{'error':str(error) if isinstance(error,Rejected) else 'invalid_command'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--db',default='arena.sqlite');args=parser.parse_args();initialize(args.db)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.db=args.db
    print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
