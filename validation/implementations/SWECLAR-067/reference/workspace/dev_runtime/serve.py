"""Neutral static server and configurable local HTTP report receiver."""
import argparse,json,mimetypes,os,time,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit
parser=argparse.ArgumentParser();parser.add_argument('--project',default='/workspace');parser.add_argument('--port',type=int,default=8080);parser.add_argument('--config');args=parser.parse_args()
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
assert os.getuid()==1000
assert int(next(x.split()[1] for x in open('/proc/self/status') if x.startswith('CapEff:')),16)==0
assert 'CLARSWE_PRIVATE_BROWSER_SENTINEL' not in os.environ
root=Path(args.project).resolve();lock=threading.Lock()
def config():return json.loads(Path(args.config).read_text()) if args.config else {}
def record(row):
 with lock:print(json.dumps(row),flush=True)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def respond(self,status,body,kind='application/json'):
  data=body if isinstance(body,bytes) else json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  path=urlsplit(self.path).path;settings=config();record({'kind':'request','method':'GET','path':self.path})
  if path in settings.get('destinations',['/chat','/schedule']):return self.respond(200,b'<!doctype html><title>Local destination</title><p>Synthetic destination</p>','text/html')
  target=(root/('index.html' if path=='/' else path.lstrip('/'))).resolve()
  if not target.is_relative_to(root) or not target.is_file():return self.respond(404,{'error':'not_found'})
  self.respond(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
 def do_POST(self):
  settings=config()
  if urlsplit(self.path).path!=settings.get('report_path','/reports'):return self.respond(404,{'error':'not_found'})
  try:body=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),1000000)))
  except (ValueError,TypeError):return self.respond(400,{'error':'invalid_json'})
  record({'kind':'request','method':'POST','path':self.path,'body':body,'idempotency_key':self.headers.get('Idempotency-Key'),'content_type':self.headers.get('Content-Type')})
  time.sleep(settings.get('delay_ms',0)/1000)
  self.respond(settings.get('status',200),{'accepted':settings.get('accepted',True),'report_id':settings.get('ack_id',body.get('report_id'))})
server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True
record({'kind':'ready','port':server.server_port,'uid':os.getuid(),'cap_eff':0,'environment_keys':sorted(os.environ)})
server.serve_forever()
