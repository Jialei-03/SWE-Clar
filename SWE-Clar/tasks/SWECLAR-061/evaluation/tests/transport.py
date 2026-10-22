from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import unquote
import base64,hashlib,hmac,json,os,secrets,select,subprocess,sys,tempfile,threading
os.environ['REPORT_PRIVATE_SENTINEL']=secrets.token_hex(24)
ROOT=Path(os.environ['CANDIDATE_ROOT']);WHITE_PATH='/usr/local/bin:/usr/bin:/bin'
class App:
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.path.chmod(0o777);self.key=secrets.token_bytes(32);self.receipts={};owner=self
  class Provider(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    row=owner.receipts.get(unquote(self.path.removeprefix('/receipts/')));body=json.dumps(row or {}).encode();self.send_response(200 if row else 404);self.end_headers();self.wfile.write(body)
  self.provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);self.thread=threading.Thread(target=self.provider.serve_forever,daemon=True);self.thread.start()
  self.db=self.path/'data.sqlite';self.cfg=self.path/'config.json';self.cfg.write_text(json.dumps({'provider':f'http://127.0.0.1:{self.provider.server_port}','provider_key':self.key.hex(),'plans':{'basic':{'amount':1700,'currency':'EUR'}}}));self.cfg.chmod(0o644)
  try:self.start();return self
  except BaseException:self.__exit__();raise
 def start(self):
  self.log=open(self.path/'server.log','a+');self.process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdout=subprocess.PIPE,stderr=self.log,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':WHITE_PATH,'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','SAAS_CONFIG':str(self.cfg),'SAAS_DATABASE':str(self.db),'PORT':'0'})
  assert select.select([self.process.stdout],[],[],10)[0],'No application startup port';line=self.process.stdout.readline();assert line.strip().isdigit(),'Application failed startup';self.url='http://127.0.0.1:'+line.strip()
  fields=dict(x.split(':',1) for x in Path(f'/proc/{self.process.pid}/status').read_text().splitlines() if ':' in x);assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
 def stop(self):
  if hasattr(self,'process'):
   self.process.terminate()
   try:self.process.wait(timeout=5)
   except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
   self.log.close()
 def __exit__(self,*args):
  self.stop();self.provider.shutdown();self.provider.server_close();self.thread.join();self.tmp.cleanup()
 def request(self,path,data=None,token=''):
  request=Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
  try:response=urlopen(request,timeout=10)
  except HTTPError as error:response=error
  with response:return response.status,response.read(),dict(response.headers)
 def ok(self,path,data=None,token=''):
  status,raw,_=self.request(path,data,token);assert 200<=status<300,(status,raw[:120]);return json.loads(raw)
 def deny(self,path,data=None,token=''):
  status,raw,_=self.request(path,data,token);assert 400<=status<500,(status,raw[:120]);assert json.loads(raw).get('error')
 def account(self,email):return self.ok('/register',{'email':email,'password':'synthetic-passphrase'})
 def seed(self,prefix,user):
  token=user['token'];self.ok('/trial',{},token);self.ok('/rooms',{'id':prefix+'-room','name':'Sample room'},token);self.ok('/content',{'id':prefix+'-content','room':prefix+'-room','title':'Sample chair','details':'A blue upholstered chair.'},token);return prefix+'-content'
 def receipt(self,account,ident,**changes):
  payload={'id':ident,'user':account['id'],'plan':'basic','amount':1700,'currency':'EUR','status':'paid',**changes};signature=hmac.new(self.key,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest();self.receipts[ident]={'payload':payload,'signature':signature};return ident
 def upload(self,user,content,ident,data,kind='image'):
  return self.ok('/assets',{'id':ident,'content':content,'kind':kind,'data':base64.b64encode(data).decode()},user['token'])
