"""Local delivery adapter. Accept only actual MP4 bytes with matching digest."""
import hashlib,json,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
private=Path(sys.argv[1])
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=50*1024*1024:raise ValueError('invalid_size')
   data=self.rfile.read(length);digest=hashlib.sha256(data).hexdigest()
   if len(data)!=length or self.headers.get('Content-Type')!='video/mp4' or self.headers.get('X-Content-SHA256')!=digest:raise ValueError('invalid_delivery')
   if data[4:8]!=b'ftyp':raise ValueError('invalid_container')
   (private/(digest+'.mp4')).write_bytes(data)
   body=json.dumps({'accepted':True,'sha256':digest}).encode();status=200
  except (ValueError,OSError):body=b'{"accepted":false}';status=400
  self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
(private/'ready.json').write_text(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port)+'/clips'}))
server.serve_forever()
