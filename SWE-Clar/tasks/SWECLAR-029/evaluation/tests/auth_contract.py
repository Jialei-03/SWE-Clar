"""Protected authentication/state checks; candidate code runs in a separate UID1000 process."""
import hashlib,json,os,subprocess,sys

def call(state,action):
 r=subprocess.run([sys.executable,'-I','/public_tests/component_runner.py'],input=json.dumps({'state':state,'action':action})+'\n',capture_output=True,text=True,timeout=10,user=1000,group=1000,extra_groups=[])
 assert r.returncode==0,r.stderr
 result=json.loads(r.stdout);assert result['ok'] and result['inputs_unchanged'],result
 return result['result']
def initial():return {'users':{'u':{'password_hash':hashlib.sha256(b'synthetic-password').hexdigest(),'two_factor_code':'123456'}}}
def auth(state=None,now=0,code='123456',password='synthetic-password'):
 return call(initial() if state is None else state,{'type':'authenticate','user_id':'u','password':password,'two_factor_code':code,'now':now})
def check(gate):
 if gate==1:
  state=auth();assert state['sessions']['u']['last_active']==0
  state=call(state,{'type':'set_connection','online':True});assert state['online'] is True
  out=call(state,{'type':'status'});assert out['result']['pending']==0 and out['result']['online'] is True
  assert isinstance(out['queue'],list) and isinstance(out['sessions'],dict)
 else:
  assert auth(password='wrong')['error']['code']=='auth_denied'
  assert auth(code='bad')['error']['code']=='auth_denied'
  state=auth();assert state['result']['two_factor_used'] is True
  assert auth(state,14*86400-1,code='bad')['result']['two_factor_used'] is False
  assert auth(state,14*86400,code='bad')['error']['code']=='auth_denied'
  assert auth(state,14*86400)['result']['two_factor_used'] is True
  event={'type':'enqueue','user_id':'u','action_id':'one','action_kind':'save','payload':{'x':1},'now':1800}
  out=call(state,event);assert out['result']['queued']=='one' and out['sessions']['u']['last_active']==1800
  assert call(state,dict(event,now=1801))['error']['code']=='session_expired'
  assert call(out,dict(event,action_id='two',now=3600))['result']['queued']=='two'
  assert call(state,dict(event,user_id='absent',now=1))['error']['code']=='session_expired'
if __name__=='__main__':
 results=[]
 for gate in [1,2]:
  try:check(gate);results.append({'ru_id':f'RU-{gate:03d}','passed':True})
  except Exception as error:results.append({'ru_id':f'RU-{gate:03d}','passed':False,'detail':str(error)})
 print(json.dumps({'harness_ok':True,'results':results}))
