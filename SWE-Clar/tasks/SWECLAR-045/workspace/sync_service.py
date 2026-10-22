"""Independently authored local synchronization fixture, to be supplied publicly."""
import json,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread,Lock

class SyncService:
    def __init__(self,database):
        self.database=str(database);self.lock=Lock()
        with sqlite3.connect(self.database) as db:db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,value,status=200):
                body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                if self.path!='/events':return self.reply({'error':'not_found'},404)
                with owner.lock,sqlite3.connect(owner.database) as db:
                    rows=[json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]
                self.reply({'events':rows})
            def do_POST(self):
                if self.path!='/sync':return self.reply({'error':'not_found'},404)
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=1_000_000:raise ValueError('size')
                    events=json.loads(self.rfile.read(length))['events']
                    if not isinstance(events,list):raise ValueError('events')
                    accepted=[];conflicts=[]
                    with owner.lock,sqlite3.connect(owner.database) as db:
                        for event in events:
                            eid=event.get('event_id')
                            if not isinstance(eid,str) or not eid.strip():raise ValueError('event id')
                            body=json.dumps(event,sort_keys=True,separators=(',',':'))
                            old=db.execute('SELECT body FROM events WHERE id=?',(eid,)).fetchone()
                            if old and old[0]!=body:conflicts.append(eid);continue
                            if not old:db.execute('INSERT INTO events VALUES (?,?)',(eid,body))
                            accepted.append(eid)
                    self.reply({'accepted_ids':accepted,'conflicting_ids':conflicts})
                except (ValueError,KeyError,TypeError,AttributeError):self.reply({'error':'invalid_request'},400)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()
