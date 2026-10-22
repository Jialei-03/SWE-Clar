from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import os,json,tempfile,threading
from solution import process_navigation_action
from router import GraphClient
ROOT=Path(__file__).parent;state_path=Path(os.environ['STATE_PATH']);lock=threading.Lock();client=GraphClient(os.environ['GRAPH_URL'])
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,mime,raw):self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path in ['/', '/app.js', '/style.css']:
            file,mime={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}[self.path];return self.send(200,mime,(ROOT/file).read_bytes())
        if self.path=='/state':
            with lock:data=state_path.read_bytes() if state_path.exists() else b'{}'
            return self.send(200,'application/json',data)
        self.send(404,'text/plain',b'Not found')
    def do_POST(self):
        if self.path!='/action':return self.send(404,'text/plain',b'Not found')
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<=65536:raise ValueError('invalid request')
            action=json.loads(self.rfile.read(n))
            with lock:
                state=json.loads(state_path.read_text()) if state_path.exists() else {};result=process_navigation_action(state,action,client)
                if 'error' not in result:
                    state_path.parent.mkdir(parents=True,exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode='w',dir=state_path.parent,delete=False) as f:json.dump(result,f);name=f.name
                    os.replace(name,state_path)
            return self.send(400 if 'error' in result else 200,'application/json',json.dumps(result).encode())
        except Exception:return self.send(400,'application/json',b'{"error":{"code":"invalid_request"}}')
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
