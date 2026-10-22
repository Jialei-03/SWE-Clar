from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
import os,json,sqlite3
from provider import SolarClient
from store import Store
ROOT=Path(__file__).parent;config=json.loads(Path(os.environ['ROOF_CONFIG']).read_text());store=Store(os.environ['ROOF_DATABASE'],SolarClient(config),config['pricing'])
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def session(self):
        c=SimpleCookie()
        try:
            c.load(self.headers.get('Cookie',''))
        except Exception:
            # A malformed or forged cookie gets a fresh anonymous session;
            # it must never become a path or database lookup primitive.
            c=SimpleCookie()
        return store.session(c['session'].value if 'session' in c else None)
    def reply(self,status,mime,data,sid=None,new=False):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        if new:self.send_header('Set-Cookie',f'session={sid}; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        sid,new=self.session();files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/vendor/leaflet.js':('vendor/leaflet.js','text/javascript'),'/vendor/leaflet.css':('vendor/leaflet.css','text/css')}
        if self.path in files:
            file,mime=files[self.path];return self.reply(200,mime,(ROOT/file).read_bytes(),sid,new)
        if self.path=='/current':return self.reply(200,'application/json',json.dumps(store.current(sid)).encode(),sid,new)
        if self.path=='/pricing':return self.reply(200,'application/json',json.dumps(config['pricing']).encode(),sid,new)
        self.reply(404,'text/plain',b'Not found',sid,new)
    def do_POST(self):
        sid,new=self.session()
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<=20000:raise ValueError('invalid_request')
            a=json.loads(self.rfile.read(n))
            if self.path=='/detect':result=store.detect(sid,a.get('address'))
            elif self.path=='/quote':result=store.quote(sid,a)
            elif self.path=='/lead':result=store.lead(sid,a)
            else:return self.reply(404,'text/plain',b'Not found',sid,new)
            self.reply(200,'application/json',json.dumps(result).encode(),sid,new)
        except PermissionError:self.reply(403,'application/json',b'{"error":"access_denied"}',sid,new)
        except Exception:self.reply(400,'application/json',b'{"error":"request_failed"}',sid,new)
http=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':http.server_port}),flush=True);http.serve_forever()
