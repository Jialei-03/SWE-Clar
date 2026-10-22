from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from pathlib import Path
import os,json
from store import Store,Error
ROOT=Path(__file__).resolve().parent;config=json.loads(Path(os.environ['CHECKIN_CONFIG']).read_text());clock_path=os.environ.get('CHECKIN_CLOCK_FILE');clock=(lambda:float(Path(clock_path).read_text())) if clock_path else None
store=Store(os.environ['CHECKIN_DATABASE'],config,clock)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def token(self):
  cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));return cookie['session'].value if 'session' in cookie else ''
 def send(self,status,data,headers=None):
  raw=data if isinstance(data,bytes) else json.dumps(data,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json' if not isinstance(data,bytes) else 'text/plain');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
  for k,v in (headers or {}).items():self.send_header(k,v)
  self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  path=urlsplit(self.path).path
  try:
   if path in ['/','/app.js','/style.css']:
    file=ROOT/('index.html' if path=='/' else path[1:]);return self.send(200,file.read_bytes(),{'Content-Type':{'/':'text/html','/app.js':'text/javascript','/style.css':'text/css'}[path]})
   user=store.actor(self.token())
   if path=='/me':return self.send(200,user)
   if path=='/sites':return self.send(200,[s for s in config['sites'] if s['active']])
   if path=='/navigation':return self.send(200,{'sections':config['sections'],'primary':'Plans'})
   if path=='/history':return self.send(200,store.history(user['id']))
   raise Error('not_found',404)
  except Error as e:self.send(e.status,{'error':e.code})
 def do_POST(self):
  try:
   a=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));path=urlsplit(self.path).path
   if not isinstance(a,dict):raise Error('invalid_request')
   if path=='/register':return self.send(200,store.register(a))
   if path=='/login':
    token=store.login(a);return self.send(200,store.actor(token),{'Set-Cookie':f'session={token}; HttpOnly; SameSite=Strict; Path=/'})
   user=store.actor(self.token())
   if path=='/checkin':return self.send(200,store.checkin(user['id'],a))
   if path=='/checkout':return self.send(200,store.checkout(user['id']))
   if path=='/logout':return self.send(200,store.logout(self.token()),{'Set-Cookie':'session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/'})
   raise Error('not_found',404)
  except Error as e:self.send(e.status,{'error':e.code})
  except (ValueError,TypeError):self.send(400,{'error':'invalid_request'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
