from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import os,json
from store import Store,Error
ROOT=Path(__file__).resolve().parent;config=json.loads(Path(os.environ['DATE_CONFIG']).read_text());store=Store(os.environ['DATE_DATABASE'],config)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def token(self):
  c=SimpleCookie();c.load(self.headers.get('Cookie',''));return c['session'].value if 'session' in c else ''
 def send(self,status,data,content_type='application/json',headers=None):
  raw=data if isinstance(data,bytes) else json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
  for k,v in (headers or {}).items():self.send_header(k,v)
  self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  u=urlsplit(self.path)
  try:
   files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/vendor/leaflet.js':('vendor/leaflet.js','text/javascript'),'/vendor/leaflet.css':('vendor/leaflet.css','text/css')}
   if u.path in files:f,kind=files[u.path];return self.send(200,(ROOT/f).read_bytes(),kind)
   actor=store.actor(self.token())
   if u.path=='/me':return self.send(200,{'actor':actor,**store.me(actor['id'])})
   if u.path=='/places':return self.send(200,store.places(parse_qs(u.query).get('q',[''])[0]))
   raise Error('not_found',404)
  except Error as e:self.send(e.status,{'error':e.code})
 def do_POST(self):
  try:
   a=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));path=urlsplit(self.path).path
   if not isinstance(a,dict):raise Error('invalid_request')
   if path=='/login':
    token=store.login(a);return self.send(200,store.actor(token),headers={'Set-Cookie':f'session={token}; HttpOnly; SameSite=Strict; Path=/'})
   actor=store.actor(self.token())
   if path in ['/credit','/purchase']:return self.send(200,store.create(actor['id'],a,path[1:]))
   raise Error('not_found',404)
  except Error as e:self.send(e.status,{'error':e.code})
  except (ValueError,TypeError):self.send(400,{'error':'invalid_request'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
