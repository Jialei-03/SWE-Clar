import hashlib,json,os,subprocess,sys
from pathlib import Path
request={'state':{'users':{'user-a':{'password_hash':hashlib.sha256(b'synthetic-password').hexdigest(),'two_factor_code':'123456'}}},'action':{'type':'authenticate','user_id':'user-a','password':'synthetic-password','two_factor_code':'123456','now':0}}
identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
def call(request):
 r=subprocess.run([sys.executable,'-I',str(Path(__file__).resolve().parent/'component_runner.py')],input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=10,env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},**identity)
 assert r.returncode==0,r.stderr
 result=json.loads(r.stdout);assert result['ok'] and result['inputs_unchanged'],result
 return result['result']
state=call(request);assert state['sessions']['user-a']['last_active']==0
state=call({'state':state,'action':{'type':'set_connection','online':True}});assert state['online'] is True
state=call({'state':state,'action':{'type':'status'}});assert state['result']['online'] is True and state['result']['pending']==0
print(json.dumps({'passed':True,'visible_authentication_and_chainable_state':True,'input_immutability':True}))
