from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import os,json
from calculator import calculate
from report import report_pdf
ROOT=Path(__file__).parent/'web'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,body,kind='application/json'):
        data=json.dumps(body,allow_nan=False).encode() if kind=='application/json' else body
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        if kind=='application/pdf':self.send_header('Content-Disposition','attachment; filename="area-report.pdf"')
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        paths={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path not in paths:return self.send(404,{'error':'not_found'})
        file,mime=paths[self.path];self.send(200,(ROOT/file).read_bytes(),mime)
    def do_POST(self):
        if self.path not in {'/calculate','/report'}:return self.send(404,{'error':'not_found'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if size<=0 or size>8192:raise ValueError('invalid_input')
            values=json.loads(self.rfile.read(size));result=calculate(values)
            if self.path=='/calculate':return self.send(200,result)
            return self.send(200,report_pdf(values),'application/pdf')
        except (ValueError,TypeError,OverflowError):return self.send(400,{'error':'invalid_input'})
class Server(ThreadingHTTPServer):request_queue_size=32
if __name__=='__main__':
    server=Server(('127.0.0.1',int(os.environ.get('PORT',0))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
