from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import os,json,urllib.parse
from store import Store
ROOT=Path(__file__).parent;config=json.loads(Path(os.environ['FOOD_CONFIG']).read_text());store=Store(os.environ['FOOD_DATABASE'],config)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,status,data,mime='application/json'):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def actor(self):return store.actor(self.headers.get('Authorization','').removeprefix('Bearer '))
    def do_GET(self):
        path=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(path.query);files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/vendor/leaflet.js':('vendor/leaflet.js','text/javascript'),'/vendor/leaflet.css':('vendor/leaflet.css','text/css')}
        try:
            if path.path in files:
                file,mime=files[path.path];return self.send(200,(ROOT/file).read_bytes(),mime)
            user=self.actor()
            if path.path=='/feed':return self.send(200,store.feed(user))
            if path.path=='/venues':return self.send(200,config['venues'])
            if path.path=='/pins':return self.send(200,store.pins(user,params.get('mode',['personal'])[0]))
            if path.path.startswith('/image/'):return self.send(200,store.image(user,path.path.removeprefix('/image/')),'image/png')
            self.send(404,{})
        except PermissionError:self.send(403,{'error':'denied'})
        except Exception:self.send(400,{'error':'request_failed'})
    def do_POST(self):
        try:
            user=self.actor();n=int(self.headers.get('Content-Length',0))
            if not 0<n<3_000_000:raise ValueError('size')
            a=json.loads(self.rfile.read(n))
            if not isinstance(a,dict):raise ValueError('body')
            method={'/upload':store.upload,'/post':store.post,'/save':store.save}.get(self.path)
            if not method:return self.send(404,{})
            self.send(200,method(user,a))
        except PermissionError:self.send(403,{'error':'denied'})
        except Exception:self.send(400,{'error':'request_failed'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
