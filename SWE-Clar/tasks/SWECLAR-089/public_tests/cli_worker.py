import json,os,sys,subprocess,tempfile,threading,select,urllib.request,urllib.error,sqlite3,traceback,importlib.util
from pathlib import Path
from copy import deepcopy
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
r=json.load(sys.stdin);ROOT=Path(r['project']).resolve()
class Provider:
 def __init__(self):
  self.calls=[];self.meetings={};self.meeting_inputs={};self.emails={};self.email_attempts=[];self.mode=None
  self.payments=deepcopy(r.get('payments',{}))
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def reply(self,status,data):
    body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def do_GET(self):
    owner.calls.append((self.command,self.path,dict(self.headers)))
    if self.headers.get('Authorization')!='Bearer synthetic-provider':return self.reply(401,{})
    from urllib.parse import unquote
    event=unquote(self.path.removeprefix('/payments/'));r=owner.payments.get(event)
    self.reply(200 if r else 404,r or {})
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));key=self.headers.get('Idempotency-Key');owner.calls.append((self.command,self.path,dict(self.headers),body))
    if self.headers.get('Authorization')!='Bearer synthetic-provider':return self.reply(401,{})
    if self.path=='/meetings':
     if owner.mode=='meeting_failure':return self.reply(503,{})
     if not key:return self.reply(400,{})
     identity={k:body[k] for k in ('booking_id','student_id','instructor_id','slot')}
     if key in owner.meeting_inputs and owner.meeting_inputs[key]!=identity:return self.reply(409,{})
     owner.meeting_inputs[key]=identity
     row={'booking_id':body['booking_id'],'join_url':'http://127.0.0.1/session/'+str(len(owner.meetings)+1)}
     owner.meetings.setdefault(key,row);return self.reply(200,owner.meetings[key])
    if self.path=='/emails':
     owner.email_attempts.append(key)
     if owner.mode=='email_failure':return self.reply(503,{})
     if owner.mode=='wrong_ack':return self.reply(200,{'accepted':True,'event_id':'mismatch'})
     if key!=body['event_id']:return self.reply(400,{})
     if key in owner.emails and owner.emails[key]!=body:return self.reply(409,{})
     owner.emails[key]=body
     if owner.mode=='accepted_then_failure':owner.mode=None;return self.reply(503,{})
     return self.reply(200,{'accepted':True,'event_id':key})
    return self.reply(404,{})
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.url='http://127.0.0.1:'+str(self.server.server_port);threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def close(self):self.server.shutdown();self.server.server_close()

class App:
 def __init__(self,work):
  self.work=work;self.db=work/'studio.sqlite';self.config=work/'config.json';self.provider=Provider();self.process=None
  state=r['state'];self.config.write_text(json.dumps({'initial_state':state,'sessions':{'session-'+key:key for key in state['users']},'provider_url':self.provider.url,'provider_token':'synthetic-provider'}));self.start()
 def start(self):
  env={'PATH':os.environ['PATH'],'HOME':'/tmp','STUDIO_DB':str(self.db),'STUDIO_CONFIG':str(self.config),'PORT':'0','PYTHONDONTWRITEBYTECODE':'1'}
  self.process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if not select.select([self.process.stdout],[],[],5)[0]:raise AssertionError('server did not start')
  line=self.process.stdout.readline()
  if not line:raise AssertionError('server failed: '+self.process.stderr.read()[-1000:])
  self.url='http://127.0.0.1:'+str(json.loads(line)['port'])+'/actions'
 def stop(self):
  if self.process:self.process.terminate();self.process.wait(timeout=5)
 def close(self):self.stop();self.provider.close()
 def request(self,action,user='student'):
  headers={'Content-Type':'application/json'}
  if user is not None:headers['Authorization']='session-student' if user=='bare' else 'Bearer session-'+user
  request=urllib.request.Request(self.url,data=json.dumps(action).encode(),headers=headers)
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=10) as response:return response.status,json.loads(response.read())
  except urllib.error.HTTPError as error:return error.code,json.loads(error.read())
 def ok(self,action,user='student'):
  status,r=self.request(action,user);assert status==200 and set(r)=={'result'},(status,r);return r['result']
 def state(self):
  with sqlite3.connect(self.db) as db:return json.loads(db.execute('SELECT state FROM studio WHERE id=1').fetchone()[0])

with tempfile.TemporaryDirectory() as temp:
 app=App(Path(temp));observations=[]
 try:
  for op in r['operations']:
   kind=op['op'];result=None
   if kind=='request':result=app.request(op['action'],op.get('user','student'))
   elif kind=='parallel':
    with ThreadPoolExecutor(max_workers=len(op['requests'])) as pool:result=list(pool.map(lambda item:app.request(item['action'],item.get('user','student')),op['requests']))
   elif kind=='restart':app.stop();app.start()
   elif kind=='mode':app.provider.mode=op.get('value')
   elif kind=='payment':app.provider.payments[op['event_id']]=op['receipt']
   observations.append({'response':result,'state':app.state(),'calls':deepcopy(app.provider.calls),'meetings':deepcopy(app.provider.meetings),'emails':deepcopy(app.provider.emails),'email_attempts':deepcopy(app.provider.email_attempts)})
  print(json.dumps({'observations':observations}))
 finally:app.close()
