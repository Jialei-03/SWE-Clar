"""Synthetic payment service and tone generator; no external service calls."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,secrets,threading,urllib.parse,hashlib,hmac,wave,math,struct,os,subprocess,sys,tempfile,select
class Fixture:
 def __init__(self,path):
  self.path=Path(path);self.accounts={'existing@example.test':{'id':'pay-existing','email':'existing@example.test'}};self.receipts={};self.hits=[];self.key=secrets.token_bytes(32);self.api_key=secrets.token_urlsafe(32);self.lock=threading.Lock();owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def execute(self):
    if self.headers.get('Authorization')!='Bearer '+owner.api_key:self.send_response(401);self.end_headers();return
    parsed=urllib.parse.urlsplit(self.path);owner.hits.append((self.command,parsed.path));result={};status=200
    with owner.lock:
     if parsed.path=='/accounts':
      email=urllib.parse.parse_qs(parsed.query).get('email',[''])[0] if self.command=='GET' else json.loads(self.rfile.read(int(self.headers['Content-Length'])))['email']
      if self.command=='POST':owner.accounts.setdefault(email,{'id':'pay-'+secrets.token_hex(6),'email':email})
      result=owner.accounts.get(email)
     elif parsed.path.startswith('/receipts/'):result=owner.receipts.get(urllib.parse.unquote(parsed.path.split('/')[-1]));status=200 if result else 404
     else:status=404
    raw=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   do_GET=execute;do_POST=execute
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  with wave.open(str(self.path/'tone.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b''.join(struct.pack('<h',int(6000*math.sin(2*math.pi*440*i/24000))) for i in range(24000*12)))
  self.config={'provider':f'http://127.0.0.1:{self.server.server_port}','api_key':self.api_key,'receipt_key':self.key.hex(),'catalog':[{'id':'tone','title':'Amber tone','artist':'Synthetic ensemble','cost':3,'filename':'tone.wav'},{'id':'second','title':'Blue tone','artist':'Other ensemble','cost':4,'filename':'tone.wav'}]};self.file=self.path/'config.json';self.file.write_text(json.dumps(self.config))
 def receipt(self,tx,email='existing@example.test',tokens=9,**extra):
  p={'transaction_id':tx,'payment_id':self.accounts[email]['id'],'status':'paid','tokens':tokens,**extra};self.receipts[tx]={'payload':p,'signature':hmac.new(self.key,json.dumps(p,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()}
 def env(self):return {'STREAM_CONFIG':str(self.file),'STREAM_DATABASE':str(self.path/'data.sqlite'),'STREAM_ASSETS':str(self.path)}
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='sweclar-listening-') as temp:
  fixture=Fixture(temp);fixture.receipt('demo-payment');p=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],env={**os.environ,**fixture.env(),'PORT':'8084'})
  print('Open http://127.0.0.1:8084; register existing@example.test with an invented password of 12+ characters; local transaction demo-payment.',flush=True)
  try:p.wait()
  except KeyboardInterrupt:p.terminate();p.wait()
  finally:fixture.close()
