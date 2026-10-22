"""Prepared synthetic source, destination and local queue service."""
import json,secrets,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread,Lock
from urllib.parse import unquote

class LocalService:
    def __init__(self,database,source):
        self.database=str(database);self.source=source;self.token=secrets.token_hex(24);self.lock=Lock()
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS destination (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,value,status=200):
                body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def authenticated(self):
                if self.headers.get('Authorization')=='Bearer '+owner.token:return True
                self.reply({'error':'unauthorized'},401);return False
            def do_GET(self):
                if not self.authenticated():return
                if self.path=='/source':return self.reply(owner.source)
                if self.path not in ['/destination','/deliveries']:return self.reply({},404)
                table='destination' if self.path=='/destination' else 'deliveries'
                with owner.lock,sqlite3.connect(owner.database) as db:
                    rows={k:json.loads(v) for k,v in db.execute('SELECT id,body FROM '+table+' ORDER BY id')}
                self.reply(rows)
            def body(self):
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1_000_000:raise ValueError('size')
                return json.loads(self.rfile.read(length))
            def do_PUT(self):
                if not self.authenticated():return
                if not self.path.startswith('/destination/'):return self.reply({},404)
                try:
                    ident=unquote(self.path[len('/destination/'):]);row=self.body()
                    if not ident or not isinstance(row,dict) or row.get('source_id')!=ident:raise ValueError('row')
                    with owner.lock,sqlite3.connect(owner.database) as db:
                        db.execute('INSERT OR REPLACE INTO destination VALUES (?,?)',(ident,json.dumps(row)))
                    self.reply({'accepted':True,'source_id':ident})
                except (ValueError,TypeError):self.reply({},400)
            def do_POST(self):
                if not self.authenticated():return
                if self.path!='/outreach':return self.reply({},404)
                try:
                    row=self.body();ident=row['delivery_id']
                    if not isinstance(ident,str) or not ident or self.headers.get('Idempotency-Key')!=ident:raise ValueError('key')
                    body=json.dumps(row,sort_keys=True)
                    with owner.lock,sqlite3.connect(owner.database) as db:
                        prior=db.execute('SELECT body FROM deliveries WHERE id=?',(ident,)).fetchone()
                        if prior and prior[0]!=body:return self.reply({},409)
                        db.execute('INSERT OR IGNORE INTO deliveries VALUES (?,?)',(ident,body))
                    self.reply({'accepted':True,'delivery_id':ident})
                except (KeyError,ValueError,TypeError):self.reply({},400)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()
