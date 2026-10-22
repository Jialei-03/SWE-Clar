from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
import os,json,urllib.parse,mimetypes
from store import Store
ROOT=Path(__file__).parent;config=json.loads(Path(os.environ['CONSOLE_CONFIG']).read_text());assets=Path(os.environ['CESIUM_ASSET_DIR']).resolve();store=Store(os.environ['CONSOLE_DATABASE'],config)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def token(self):
        cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''));return cookies['session'].value if 'session' in cookies else None
    def send(self,status,data,mime='application/json',token=None):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        if token is not None:self.send_header('Set-Cookie',f'session={token}; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        url=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(url.query);files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        try:
            if url.path in files:
                file,mime=files[url.path];return self.send(200,(ROOT/file).read_bytes(),mime)
            if url.path.startswith('/cesium/'):
                file=(assets/urllib.parse.unquote(url.path.removeprefix('/cesium/'))).resolve()
                if not file.is_relative_to(assets) or not file.is_file():return self.send(404,{})
                return self.send(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            user=store.actor(self.token())
            if url.path=='/me':return self.send(200,user)
            if url.path=='/locations':return self.send(200,store.locations(q.get('q',[''])[0]))
            if url.path=='/tracks':return self.send(200,store.tracks())
            if url.path=='/rewind':return self.send(200,store.rewind(q.get('id',[''])[0],q.get('at',[''])[0]))
            self.send(404,{})
        except PermissionError:self.send(403,{'error':'login_required'})
        except LookupError:self.send(404,{'error':'not_found'})
        except Exception:self.send(400,{'error':'request_failed'})
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<=10000:raise ValueError('size')
            a=json.loads(self.rfile.read(n))
            if not isinstance(a,dict):raise ValueError('body')
            if self.path=='/login':
                token,user=store.login(a);return self.send(200,user,token=token)
            if self.path=='/logout':store.logout(self.token());return self.send(200,{'logged_out':True},token='')
            self.send(404,{})
        except PermissionError:self.send(403,{'error':'invalid_login'})
        except Exception:self.send(400,{'error':'request_failed'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
