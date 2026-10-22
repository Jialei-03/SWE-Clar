import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from contract_support import call
from auth_contract import auth

def faithful_requests(requests,expected):
 return all(path=='/apply' and ident==body['action_id'] and all(body.get(k)==v for k,v in expected[ident].items()) for path,ident,body in requests)

def check():
 requests=[];failure={'mode':'http'}
 class Receiver(BaseHTTPRequestHandler):
  def do_POST(self):
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,self.headers.get('Idempotency-Key'),data))
   bad=data['action_id']=='second' and failure['mode']
   self.send_response(503 if bad=='http' else 200);self.end_headers();self.wfile.write(json.dumps({'accepted':True,'action_id':'wrong' if bad=='ack' else data['action_id']}).encode())
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Receiver);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  state=auth();endpoint=f'http://127.0.0.1:{server.server_port}/apply'
  expected={}
  for ident,kind in [('first','save'),('second','email'),('third','upload')]:
   payload={'value':ident,'nested':{'text':'Synthetic 雨','items':[1,False,None]}}
   expected[ident]=dict(action_id=ident,user_id='u',kind=kind,payload=payload)
   state=call(state,{'type':'enqueue','user_id':'u','action_id':ident,'action_kind':kind,'payload':payload,'now':1},None)
  replay={'type':'enqueue','user_id':'u','action_id':'first','action_kind':'save','payload':expected['first']['payload'],'now':1}
  state=call(state,replay,None);assert len(state['queue'])==3
  conflict=call(state,dict(replay,payload={'value':'different'}),None);assert conflict['error']['code']=='queue_conflict'
  action={'type':'flush','user_id':'u','now':2}
  assert call(state,action,None,endpoint)['error']['code']=='offline' and requests==[]
  state=call(state,{'type':'set_connection','online':True},None)
  other={'action_id':'other-user','user_id':'v','kind':'save','payload':{'synthetic':'other'},'status':'pending'}
  state['queue'].append(other)
  assert call(state,dict(action,user_id='absent'),None,endpoint)['error']['code']=='session_expired' and requests==[]
  state=call(state,action,None,endpoint);assert state['error']['code']=='sync_failed' and [q['status'] for q in state['queue']]==['applied','pending','pending','pending']
  failure['mode']='ack';state=call(state,dict(action,now=3),None,endpoint);assert state['error']['code']=='sync_failed'
  failure['mode']=None;state=call(state,dict(action,now=4),None,endpoint)
  assert [q['status'] for q in state['queue']]==['applied']*3+['pending']
  assert [r[1] for r in requests]==['first','second','second','second','third']
  assert state['queue'][-1]==other
  assert faithful_requests(requests,expected),'Every retry sends the complete originally enqueued intent'
  state=call(state,dict(action,now=5),None,endpoint);assert len(requests)==5
 finally:server.shutdown();server.server_close()
