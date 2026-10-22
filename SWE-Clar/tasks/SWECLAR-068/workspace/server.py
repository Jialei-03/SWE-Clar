from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import os,json
from solution import evaluate_indicator
ROOT=Path(__file__).parent
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,value,mime='application/json'):
  data=value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/':return self.send(200,(ROOT/'index.html').read_bytes(),'text/html')
  self.send(404,{'error':'not_found'})
 def do_POST(self):
  try:
   if self.path!='/evaluate':return self.send(404,{'error':'not_found'})
   count=int(self.headers.get('Content-Length','0'))
   if not 0<count<100000:raise ValueError('body')
   value=json.loads(self.rfile.read(count));self.send(200,evaluate_indicator(value['config'],value['context']))
  except Exception:self.send(400,{'error':'evaluation_failed'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8080'))),Handler);print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
