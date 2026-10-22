from copy import deepcopy
import hashlib
from candidate_proxy import call,cli
from password_contract import assert_password_verifier

def base():return {'question_pool':{q:{'weight':w} for q,w in zip(['q1','q2','q3','q4','q5'],[3,3,2,1,1])},'curated_stocks':{'DEMO':{}}}
def register(uid='u',email=' A@example.net '):return {'type':'register','user_id':uid,'email':email,'password':'synthetic-pass','name':uid}
def user():return call(base(),register())
def denied(state,action):
 out=call(state,action);assert out.get('error')
 for k,v in state.items():
  if k not in ('result','error'):assert out.get(k)==v
 return out

def test_ru_001_entry_and_real_persistence():
 denied(base(),{'type':'unknown'})
 rows=cli(base(),[{'command':'act','value':register()},{'command':'show'},{'command':'init','value':{}},{'command':'show'}])
 assert all(r['returncode']==0 for r in rows)
 assert rows[1]['output']['result']['user_id']=='u' and 'users' not in rows[1]['output']
 assert rows[2]['output']['users']['u']['email']=='a@example.net'
 assert rows[3]['output'].get('error') and rows[4]['output']==rows[2]['output']

def test_ru_002_hash_sessions_and_account_access():
 state=user();encoded=state['users']['u']['password_hash'];assert isinstance(encoded,str) and encoded not in {hashlib.sha256(b'synthetic-pass').hexdigest(),hashlib.sha512(b'synthetic-pass').hexdigest(),hashlib.md5(b'synthetic-pass').hexdigest(),'synthetic-pass'}
 assert_password_verifier(encoded,register()['password'])
 # Independent passwords prevent a fixture-specific verifier from passing.
 for password in ['different-local-pass','Cafe\u0301-\uff21-test']:
  registered=call(base(),{**register(),'password':password})
  assert_password_verifier(registered['users']['u']['password_hash'],password)
 second=call(base(),register());assert encoded!=second['users']['u']['password_hash']
 for changes in ({'email':'missing-at'},{'email':'a @example.net'},{'email':'@x'},{'password':' '},{'password':None}):denied(base(),{**register(),**changes})
 denied(state,register('v','a@EXAMPLE.NET'));denied(state,register('u','other@example.net'))
 denied(state,{'type':'login','user_id':'u','password':'wrong'})
 state=call(state,register('v','v@example.net'));state=call(state,{'type':'login','user_id':'u','password':'synthetic-pass'});token=state['result']['token'];assert isinstance(token,str) and bool(token)
 state=call(state,{'type':'login','user_id':'u','password':'synthetic-pass'});other=state['result']['token'];assert token!=other
 account=call(state,{'type':'account','token':token,'user_id':'v'})['result'];assert account['user_id']=='u' and account['email']=='a@example.net' and account['lifetime'] is False
 assert 'password_hash' not in account and 'users' not in account
 denied(state,{'type':'account','token':'invented'})
 state=call(state,{'type':'logout','token':token});denied(state,{'type':'account','token':token});assert call(state,{'type':'account','token':other})['result']['user_id']=='u'
 rows=cli(base(),[{'command':'act','value':register()},{'command':'act','value':{'type':'login','user_id':'u','password':'synthetic-pass'}},{'command':'act','value':{'type':'account','token':{'observation':2,'path':['result','token']}}}])
 assert rows[-1]['output']['result']['email']=='a@example.net'
 assert all('users' not in x['output'] and 'password_hash' not in str(x['output']) for x in rows[1:])

def payment():return {'type':'stripe_event','user_id':'u','event_id':'e','stripe_session_id':'s','purchase_type':'lifetime','confirmed':True}
def test_ru_003_lifetime_audit_and_replay():
 state=user();event=payment()
 for change in ({'confirmed':False},{'confirmed':1},{'purchase_type':'monthly'},{'user_id':'missing'},{'stripe_session_id':''}):denied(state,{**event,**change})
 state=call(state,event);assert state['entitlements']['u']=='lifetime' and state['result']['granted'] is True
 before=deepcopy(state);replay=call(state,event);assert replay['result']['duplicate'] is True and replay['result']['granted'] is False
 assert replay['payments']==before['payments'] and replay['entitlements']==before['entitlements']
 denied(state,{**event,'stripe_session_id':'changed'})
 state=call(state,{'type':'login','user_id':'u','password':'synthetic-pass'});assert call(state,{'type':'account','token':state['result']['token'],'lifetime':False})['result']['lifetime'] is True
 rows=cli(base(),[{'command':'act','value':register()},{'command':'act','value':event},{'command':'act','value':event},{'command':'show'}]);assert rows[3]['output']['result']['duplicate'] is True and len(rows[4]['output']['payments'])==1

def report():return {'type':'generate_report','symbol':'DEMO','date':'2026-02-28','movement_pct':2,'sections':{'reason':'Demand changed','movement':'Price rose','risk_boundary':'Loss remains possible','watch_next':'Review the next statement'}}
def test_ru_004_finite_text_policy_and_report_values():
 action=report();state=base()
 for move in (-3,0,2.5):
  out=call(state,{**action,'movement_pct':move});r=out['result'];assert r['illustration']['allocation']==1000 and r['illustration']['change']==10*move
  assert out['reports']['2026-02-28:DEMO']['reason']==action['sections']['reason']
 for change in ({'symbol':'OTHER'},{'date':'2026-02-30'},{'date':'2026-2-28'},{'movement_pct':True},{'movement_pct':float('inf')}):denied(state,{**action,**change})
 for key in action['sections']:
  for value in ('',None,'GuArAnTeEd ReTuRn tomorrow','institutional-grade prediction'):denied(state,{**action,'sections':{**action['sections'],key:value}})
 for wording in ('Trading activity increased','A stronger business could still lose money','We describe uncertainty simply'):
  assert 'error' not in call(state,{**action,'sections':{**action['sections'],'reason':wording}})
 rows=cli(base(),[{'command':'act','value':action},{'command':'show'}]);assert rows[2]['output']['reports']['2026-02-28:DEMO']['illustration']['change']==20

def screen(answers,stamp=100):return {'type':'screen','user_id':'u','answers':dict(zip(['q1','q2','q3','q4'],answers)),'timestamp':stamp}
def test_ru_005_weighted_tiers_retake_and_events():
 for answers,tier in [([True,True,True,False],'Pro Beta'),([True,False,False,True],'Basic Beta'),([True,False,False,False],'Waitlist')]:
  out=call(user(),screen(answers));assert out['result']['tier']==tier and out['result']['score_hidden'] is True
  assert not set(out['result'])&{'score','answers','weights'}
 state=call(user(),screen([False]*4));denied(state,screen([True]*4,604899.9));state=call(state,screen([True]*4,604900));denied(state,screen([True]*4,2000000))
 for action in [screen([1,False,False,False]),{**screen([True]*4),'answers':{'unknown':True}},screen([True]*4,True),screen([True]*4,-1)]:denied(user(),action)
 action={'type':'track','user_id':'u','event':'open_report','metro':'Synthetic City','timestamp':0}
 out=call(user(),action);assert all(out['events'][-1][k]==action[k] for k in ('user_id','event','metro','timestamp'))
 for change in ({'user_id':'missing'},{'timestamp':True},{'timestamp':float('inf')},{'metro':''}):denied(user(),{**action,**change})
 rows=cli(base(),[{'command':'act','value':register()},{'command':'act','value':screen([True,False,False,True])},{'command':'act','value':action},{'command':'show'}]);assert rows[-1]['output']['screening']['u']['tier']=='Basic Beta' and rows[-1]['output']['events'][-1]['timestamp']==0
