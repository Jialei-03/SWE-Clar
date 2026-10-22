from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import os,json
from store import Store
ROOT=Path(__file__).parent;config=json.loads(Path(os.environ['KIOSK_CONFIG']).read_text());store=Store(os.environ['KIOSK_DATABASE'],config)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,status,data,mime='application/json'):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def actor(self):return store.actor(self.headers.get('Authorization','').removeprefix('Bearer '))
    def do_GET(self):
        files={'/sw.js':('sw.js','text/javascript'),'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path in files:
            name,mime=files[self.path];return self.send(200,(ROOT/name).read_bytes(),mime)
        try:
            actor=self.actor()
            if self.path=='/snapshot':return self.send(200,store.snapshot(actor))
            if self.path.startswith('/asset/'):
                key=self.path.removeprefix('/asset/')
                if key not in store.snapshot(actor)['assets']:return self.send(404,{})
                return self.send(200,Path(config['assets'][key]).read_bytes(),'image/svg+xml')
            if self.path=='/analytics':
                if actor['role'] not in ['admin','editor']:raise PermissionError('denied')
                with store.db() as db:rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM events ORDER BY rowid')]
                return self.send(200,rows)
            self.send(404,{})
        except PermissionError:self.send(403,{'error':'denied'})
        except Exception:self.send(400,{'error':'request_failed'})
    def do_POST(self):
        try:
            actor=self.actor();n=int(self.headers.get('Content-Length',0))
            if not 0<n<=100000:raise ValueError('size')
            a=json.loads(self.rfile.read(n))
            if not isinstance(a,dict):raise ValueError('body')
            methods={'/edit':store.edit,'/publish':store.publish,'/track':store.track,'/settings':store.settings}
            if self.path not in methods:return self.send(404,{})
            self.send(200,methods[self.path](actor,a))
        except PermissionError:self.send(403,{'error':'denied'})
        except Exception:self.send(400,{'error':'request_failed'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
