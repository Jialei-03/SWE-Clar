from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import secrets,json,hmac,hashlib,threading
class LocalProvider:
 def __init__(self):
  self.token=secrets.token_hex(16);self.key=secrets.token_bytes(32);self.calls=[];self.payments={};self.fault=None
  self.places=[{'id':'coffee-a','name':'Clear coffee','type':'coffee','latitude':.03,'longitude':.04},{'id':'pub-a','name':'Clear pub','type':'pub','latitude':.05,'longitude':.06},{'id':'shop-a','name':'Clear shop','type':'shop','latitude':.07,'longitude':.08}]
  provider=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));provider.calls.append((self.path,body));status=200
    if self.headers.get('Authorization')!='Bearer '+provider.token:status=403;data={}
    elif self.path=='/places/search':data={'places':provider.places}
    elif self.path=='/places/get':data={'place':next((p for p in provider.places if p['id']==body.get('id')),None)}
    elif self.path=='/payments/confirm':
     if provider.fault=='unavailable':status=503;data={}
     else:
      payload={**body,'status':'paid'}
      if body['id'] in provider.payments and provider.payments[body['id']]!=payload:status=409;data={}
      else:
       provider.payments[body['id']]=payload
       if provider.fault=='wrong_user':payload={**payload,'user':'foreign'}
       if provider.fault=='wrong_amount':payload={**payload,'amount_minor':1}
       if provider.fault=='wrong_id':payload={**payload,'id':'different-confirmation'}
       if provider.fault=='wrong_product':payload={**payload,'product_id':'five' if body['product_id']!='five' else 'one'}
       if provider.fault=='wrong_currency':payload={**payload,'currency':'USD'}
       if provider.fault=='unpaid':payload={**payload,'status':'pending'}
       signature=hmac.new(provider.key,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
       data={'payload':payload,'signature':signature if provider.fault!='signature' else '0'*64}
       if provider.fault=='lost_response':status=503;data={};provider.fault=None
    else:status=404;data={}
    raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def close(self):self.server.shutdown();self.server.server_close()

# RPC keeps this synthetic provider in an ordinary-user process; assertions stay with its caller.
class Provider:
 def __init__(self):
  import os,subprocess,sys
  identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
  self.process=subprocess.Popen([sys.executable,'-I',__file__,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},**identity)
  ready=json.loads(self.process.stdout.readline());self.url=ready['url'];self.token=ready['token'];self.key=bytes.fromhex(ready['key'])
 def rpc(self,op,**values):
  self.process.stdin.write(json.dumps({'op':op,**values})+'\n');self.process.stdin.flush();return json.loads(self.process.stdout.readline())
 @property
 def calls(self):return self.rpc('calls')
 @property
 def payments(self):return self.rpc('payments')
 @property
 def fault(self):return self.rpc('fault')
 @fault.setter
 def fault(self,value):self.rpc('set_fault',value=value)
 def close(self):
  if self.process.poll() is None:self.rpc('close');self.process.wait(timeout=5)
  self.process.stdin.close();self.process.stdout.close();self.process.stderr.close()
if __name__=='__main__':
 import sys
 if '--worker' in sys.argv:
  provider=LocalProvider();print(json.dumps({'url':provider.url,'token':provider.token,'key':provider.key.hex()}),flush=True)
  try:
   for line in sys.stdin:
    command=json.loads(line);op=command['op']
    if op=='close':print('null',flush=True);break
    if op=='set_fault':provider.fault=command['value'];value=None
    else:value=getattr(provider,op)
    print(json.dumps(value),flush=True)
  finally:provider.close()
