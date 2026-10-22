"""Benchmark-owned local delivery endpoint; no external messages are sent."""
import json,sqlite3,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

class NotificationFixture:
 def __init__(self,path,host='127.0.0.1',port=0):
  self.path=str(path);self.lock=threading.Lock();self.failures={}
  with sqlite3.connect(self.path) as db:db.execute('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,channel TEXT,recipient TEXT,body TEXT)')
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def reply(self,status,value):
    body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def do_GET(self):
    self.reply(200,{'ready':True}) if self.path=='/health' else self.reply(404,{'error':'not_found'})
   def do_POST(self):
    if self.path!='/messages':return self.reply(404,{'error':'not_found'})
    try:
     size=int(self.headers.get('Content-Length','0'))
     if not 0<size<=65536:raise ValueError()
     data=json.loads(self.rfile.read(size))
     if set(data)!={'id','channel','recipient','body'} or any(not isinstance(v,str) or not v for v in data.values()):raise ValueError()
     if data['channel'] not in {'sms','email','manager_email'}:raise ValueError()
    except (ValueError,TypeError):return self.reply(400,{'error':'invalid_delivery'})
    with owner.lock,sqlite3.connect(owner.path) as db:
     existing=db.execute('SELECT channel,recipient,body FROM receipts WHERE id=?',(data['id'],)).fetchone()
     values=(data['channel'],data['recipient'],data['body'])
     if existing:
      if existing!=values:return self.reply(409,{'error':'idempotency_conflict'})
      return self.reply(200,{'accepted':True,'duplicate':True})
     remaining=owner.failures.get(data['channel'],0)
     if remaining:
      owner.failures[data['channel']]=remaining-1;return self.reply(503,{'error':'temporary_failure'})
     db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(data['id'],*values))
    self.reply(200,{'accepted':True,'duplicate':False})
   def log_message(self,*args):pass
  self.server=ThreadingHTTPServer((host,port),Handler);self.url=f'http://{host}:{self.server.server_port}'
 def start(self):
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
 def receipts(self):
  with self.lock,sqlite3.connect(self.path) as db:
   db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute('SELECT * FROM receipts ORDER BY id')]
 def fail_next(self,channel,count=1):
  with self.lock:self.failures[channel]=count
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
