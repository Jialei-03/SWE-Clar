"""Local scheduling HTTP entrypoint; dependencies are provisioned by the benchmark."""
import argparse,json,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.error import URLError
from service import signup,tick
from store import connect

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
 config=json.load(open(args.config));db_path=config['database'];sink=config['notification_url'];timezone=config['timezone']
 with connect(db_path):pass
 class Handler(BaseHTTPRequestHandler):
  def respond(self,status,data):
   body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  def do_GET(self):
   if self.path=='/health':return self.respond(200,{'ready':True})
   if self.path=='/state':
    with connect(db_path) as db:state={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in ['employees','shifts','signups']}
    return self.respond(200,state)
   self.respond(404,{'error':'not_found'})
  def do_POST(self):
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=65536:raise ValueError('invalid_payload')
    data=json.loads(self.rfile.read(length))
    if self.path=='/signups':result=signup(db_path,sink,data)
    elif self.path=='/tick':result=tick(db_path,sink,data['now'],timezone)
    else:return self.respond(404,{'error':'not_found'})
    self.respond(200,result)
   except (ValueError,KeyError,TypeError,sqlite3.IntegrityError):self.respond(400,{'error':'invalid_request'})
   except (URLError,TimeoutError,RuntimeError):self.respond(503,{'error':'delivery_unavailable'})
  def log_message(self,*args):pass
 ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__':main()
