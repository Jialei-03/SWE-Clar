"""Synthetic loopback HTTP service for local adapter development."""
import argparse,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
 count=0
 def send(self,value,status=200):self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode())
 def do_GET(self):
  if self.path=='/services':self.send([{'id':'consultation','title':'General consultation','available_slots':['09:00','11:00']}])
  else:self.send({'error':'not_found'},404)
 def do_POST(self):
  try:
   data=b''
   if self.headers.get('Transfer-Encoding','').lower()=='chunked':
    while True:
     n=int(self.rfile.readline().split(b';',1)[0],16)
     if not n:self.rfile.readline();break
     data+=self.rfile.read(n);self.rfile.read(2)
   else:data=self.rfile.read(int(self.headers.get('Content-Length','0')))
   body=json.loads(data)
   if self.path=='/login':self.send({'id':'synthetic-user'})
   elif self.path=='/appointments':
    Handler.count+=1;self.send({'id':f'appointment-{Handler.count}','service_id':body['service_id'],'slot':body['slot']})
   else:self.send({'error':'not_found'},404)
  except (ValueError,KeyError,TypeError):self.send({'error':'invalid_request'},400)
 def log_message(self,*a):pass
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8080);a=p.parse_args();s=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);print(json.dumps({'url':f'http://127.0.0.1:{s.server_port}'}),flush=True);s.serve_forever()
