"""Actual local HTTP hiring application; no production services or original assets."""
import argparse,hmac,json,secrets,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from common import Problem,require,fields
from storage import connect,initialize,password_hash,public_user
import marketplace

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,payload,kind='application/json',filename=None):
  data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else payload
  self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
  if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
  self.end_headers();self.wfile.write(data)
 def do_GET(self):self.handle_request()
 def do_POST(self):self.handle_request()
 def do_PUT(self):self.handle_request()
 def handle_request(self):
  try:
   route=urlparse(self.path);path=route.path
   static={'/':('index.html','text/html'),'/ui.js':('ui.js','text/javascript'),'/style.css':('style.css','text/css')}
   if self.command=='GET' and path in static:
    name,kind=static[path];self.send(200,(Path(__file__).parent/'web'/name).read_bytes(),kind);return
   if self.command=='GET' and path=='/health':self.send(200,{'ok':True});return
   body={}
   if self.command in ['POST','PUT']:
    size=int(self.headers.get('Content-Length','0'));require(0<size<=400000);body=json.loads(self.rfile.read(size),parse_constant=lambda _:None);require(isinstance(body,dict))
   query=parse_qs(route.query,keep_blank_values=True);require(all(len(v)==1 for v in query.values()));query={k:v[0] for k,v in query.items()}
   with connect(self.server.db) as db:
    db.execute('BEGIN IMMEDIATE');result=self.dispatch(db,path,query,body)
   if isinstance(result,tuple):data,kind,filename=result;self.send(200,data,kind,filename)
   else:self.send(200,result)
  except Problem as error:self.send(error.status,{'error':{'code':error.code}})
  except (ValueError,TypeError,UnicodeError):self.send(400,{'error':{'code':'invalid'}})
  except sqlite3.Error:self.send(503,{'error':{'code':'storage_unavailable'}})
 def dispatch(self,db,path,query,body):
  method=self.command
  if method=='POST' and path=='/api/login':
   fields(query,[]);fields(body,['id','password']);require(isinstance(body['id'],str) and isinstance(body['password'],str))
   row=db.execute('SELECT * FROM users WHERE id=?',(body['id'],)).fetchone();require(row is not None and hmac.compare_digest(row['password_hash'],password_hash(body['password'],row['password_hash'].split('$')[0])),'unauthorized',401)
   token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(token,row['id']));return {'token':token,'user':public_user(row)}
  token=self.headers.get('Authorization','');require(token.startswith('Bearer '),'unauthorized',401)
  user=db.execute('SELECT users.* FROM users JOIN sessions ON sessions.user_id=users.id WHERE sessions.token=?',(token[7:],)).fetchone();require(user is not None,'unauthorized',401)
  if method=='POST' and path=='/api/logout':
   fields(query,[]);fields(body,[]);db.execute('DELETE FROM sessions WHERE token=?',(token[7:],));return {'ok':True}
  if method=='GET' and path=='/api/me':
   fields(query,[]);return {'user':public_user(user),'clock_ms':json.loads(db.execute("SELECT value FROM meta WHERE key='clock_ms'").fetchone()[0])}
  if method in ['POST','PUT']:fields(query,[])
  return marketplace.dispatch(db,user,method,path,query,body)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--db',type=Path,required=True);parser.add_argument('--fixtures',type=Path,default=Path('fixtures/demo.json'));args=parser.parse_args();initialize(args.db,args.fixtures)
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True;server.db=args.db
 print(json.dumps({'port':server.server_port}),flush=True)
 try:server.serve_forever()
 finally:server.server_close()
if __name__=='__main__':main()
