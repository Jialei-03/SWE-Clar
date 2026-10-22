"""Benchmark-managed synthetic key, workspace and local acknowledgement service."""
import hashlib,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def serve():
 class Handler(BaseHTTPRequestHandler):
  def reply(self,status,value):
   raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  def do_GET(self):self.reply(200,{'ready':True}) if self.path=='/health' else self.reply(404,{'error':'not_found'})
  def do_POST(self):
   if self.path!='/apply':return self.reply(404,{'error':'not_found'})
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=1048576:raise ValueError()
    data=json.loads(self.rfile.read(size))
    if set(data)!={'action_id','user_id','kind','payload'} or not data['action_id'] or self.headers.get('Idempotency-Key')!=data['action_id']:raise ValueError()
   except (ValueError,TypeError):return self.reply(400,{'accepted':False})
   self.reply(200,{'accepted':True,'action_id':data['action_id']})
  def log_message(self,*args):pass
 ThreadingHTTPServer(('127.0.0.1',38930),Handler).serve_forever()
def main():
 def ready():
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:38930/health',timeout=.5) as r:return json.load(r)=={'ready':True}
 try:ok=ready()
 except OSError:ok=False
 if not ok:
  p=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--serve'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,start_new_session=True)
  for _ in range(100):
   try:
    if ready():break
   except OSError:pass
   if p.poll() is not None:raise RuntimeError('Sync fixture exited')
   time.sleep(.03)
  else:raise RuntimeError('Sync fixture unavailable')
 code='''import hashlib,json,os
from pathlib import Path
root=Path('/workspace/runtime');root.mkdir(exist_ok=True);(root/'bundles').mkdir(exist_ok=True)
config=root/'store.json'
if not config.exists():
 config.write_text(json.dumps({'root':str(root/'bundles'),'key_hex':os.urandom(32).hex()}));config.chmod(0o600)
request=root/'example.jsonl'
if not request.exists():
 state={'users':{'user-a':{'password_hash':hashlib.sha256(b'synthetic-password').hexdigest(),'two_factor_code':'123456'}},'assignments':{'user-a':['job-a']},'remote_jobs':{'job-a':{'data':{'note':'Synthetic field bundle'}}}}
 action={'type':'authenticate','user_id':'user-a','password':'synthetic-password','two_factor_code':'123456','now':0}
 request.write_text(json.dumps({'state':state,'action':action,'store':json.loads(config.read_text()),'endpoint':'http://127.0.0.1:38930/apply'})+'\\n');request.chmod(0o600)
exclude=Path('/workspace/.git/info/exclude')
if exclude.parent.exists():
 text=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in text.splitlines():exclude.write_text(text+'\\n/runtime/\\n')
'''
 identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
 subprocess.run([sys.executable,'-I','-c',code],check=True,**identity)
 print(json.dumps({'passed':True,'synthetic_key_ready':True,'local_sync_ready':True,'example_request_ready':True}))
if __name__=='__main__':serve() if '--serve' in sys.argv else main()
