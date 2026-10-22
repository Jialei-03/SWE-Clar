"""Local synthetic signed-receipt fixture. No real payments."""
import hashlib,hmac,json,secrets,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote
from pathlib import Path
key=secrets.token_hex(32);plans={'basic':{'amount':1700,'currency':'EUR'}};receipts={}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def reply(self,status,value):
  body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if self.path=='/health':return self.reply(200,{'ok':True})
  value=receipts.get(unquote(self.path.removeprefix('/receipts/')));self.reply(200 if value else 404,value or {})
 def do_POST(self):
  try:
   if self.path!='/issue':raise ValueError()
   request=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));plan=plans[request['plan']]
   payload={'id':request['id'],'user':request['user'],'plan':request['plan'],'status':'paid',**plan};signature=hmac.new(bytes.fromhex(key),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest();receipts[payload['id']]={'payload':payload,'signature':signature};self.reply(200,{'payment_id':payload['id']})
  except (KeyError,ValueError,TypeError):self.reply(400,{'error':'invalid_fixture_request'})
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
root=Path('/workspace/runtime');root.mkdir(exist_ok=True)
(root/'config.json').write_text(json.dumps({'provider':f'http://127.0.0.1:{server.server_port}','provider_key':key,'plans':plans}))
print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
