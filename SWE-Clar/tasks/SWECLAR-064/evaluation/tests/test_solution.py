from copy import deepcopy
import json
from candidate_proxy import call,cli

SECRETS=['+15550102001','+15550102002','+15550102003','code-red','code-blue','code-green']
def base():return {'users':{'a':{'phone':SECRETS[0],'otp':SECRETS[3],'verified':False},'b':{'phone':SECRETS[1],'otp':SECRETS[4],'verified':True},'org':{'phone':SECRETS[2],'otp':SECRETS[5],'verified':True,'approved_organizer':True},'other':{'verified':True,'approved_organizer':True}},'events':{},'matches':{},'messages':[]}
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k not in {'phone','otp','result','error','registration_status'}}
 if isinstance(x,list):return [clean(v) for v in x]
 return x
def same(a,b):
 for key in ['users','events','matches','messages','reports','admin_alerts']:
  default={} if key in ['users','events','matches'] else [];assert clean(a.get(key,default))==clean(b.get(key,default)),key
def private(out):
 wire=json.dumps(out);assert not any(secret in wire for secret in SECRETS);assert '"phone"' not in wire and '"otp"' not in wire

def ok(s,a):
 out=call(s,a);assert 'error' not in out,out;private(out);return out
def denied(s,a):
 out=call(s,a);assert out.get('error',{}).get('code'),out;same(s,out);private(out);return out
def event(s=None,lead=1,follow=1):return ok(base() if s is None else s,dict(type='create_event',organizer_id='org',event_id='e',capacity={'lead':lead,'follow':follow}))
def register(s,u,role):return ok(s,dict(type='register_event',event_id='e',user_id=u,role=role))
def matched(s=None,a='a',b='b'):
 s=ok(base() if s is None else s,dict(type='express_interest',user_id=a,target_id=b));return ok(s,dict(type='express_interest',user_id=b,target_id=a))
def listed_pairs(records):
 pairs=[]
 for record in records:
  assert record['active'] is True and len(record['users'])==2
  pair=frozenset(record['users']);assert len(pair)==2;pairs.append(pair)
 assert len(pairs)==len(set(pairs))
 return set(pairs)
def matches(s,u):
 records=ok(s,dict(type='list_matches',user_id=u))['result']['matches']
 expected={frozenset(m['users']) for m in s['matches'].values() if m.get('active') and u in m['users']}
 assert listed_pairs(records)==expected
 return records
def rows(observations):
 assert all(x['returncode']==0 and isinstance(x['output'],dict) for x in observations),observations
 output=[x['output'] for x in observations]
 for x in output:private(x)
 return output

def test_ru_001_entry_privacy():
 s=base();out=call(s,{'type':'unknown'});assert isinstance(out,dict);denied(s,{'type':'unknown'});denied(s,{})
 output=rows(cli(s,[{'command':'show'},{'command':'act','value':[]},{'command':'show'}]));assert output[0]==output[1]==output[3];assert output[2]['error']['code']

def test_ru_002_auth_profiles():
 s=base()
 for otp in ['bad','',None]:denied(s,dict(type='verify_otp',user_id='a',otp=otp))
 profile=dict(type='update_profile',user_id='a',dance_style='salsa',skill_level='beginner',preferred_role='lead');denied(s,profile)
 verified=ok(s,dict(type='verify_otp',user_id='a',otp=SECRETS[3]));assert verified['result']['verified'] is True and verified['users']['a']['verified'] is True
 out=ok(verified,{**profile,'phone':'forged','approved_organizer':True,'verified':False});assert out['users']['a']['verified'] is True and not out['users']['a'].get('approved_organizer');assert all(out['result']['profile'][k]==profile[k] for k in ['dance_style','skill_level','preferred_role'])
 denied(verified,{**profile,'preferred_role':'invalid'});denied(verified,{**profile,'skill_level':''});denied(s,dict(type='verify_otp',user_id='missing',otp='bad'))
 operations=[{'command':'act','value':dict(type='verify_otp',user_id='a',otp='bad')},{'command':'act','value':dict(type='verify_otp',user_id='a',otp=SECRETS[3])},{'command':'act','value':profile},{'command':'act','value':dict(type='verify_otp',user_id='b',otp=SECRETS[4])},{'command':'show'}]
 output=rows(cli(s,operations));assert output[1]['error']['code'];assert output[2]['result']['verified'] is True;assert output[4]['result']['verified'] is True;assert output[5]['users']['a']['profile']['dance_style']=='salsa'

def test_ru_003_events():
 s=base();denied(s,dict(type='create_event',organizer_id='b',event_id='e',capacity={'lead':1,'follow':1}))
 forged=deepcopy(s);forged['users']['b']['approved_organizer']='yes';denied(forged,dict(type='create_event',organizer_id='b',event_id='e',capacity={'lead':1,'follow':1}))
 for capacity in [{'lead':-1,'follow':1},{'lead':True,'follow':1},{'lead':1}]:denied(s,dict(type='create_event',organizer_id='org',event_id='e',capacity=capacity))
 s=event();denied(s,dict(type='create_event',organizer_id='org',event_id='e',capacity={'lead':2,'follow':2}));s=register(s,'a','lead');assert s['registration_status']=='confirmed';s=register(s,'b','lead');assert s['registration_status']=='waitlisted';assert len(s['events']['e']['attendees'])==1 and len(s['events']['e']['waitlist'])==1
 again=call(s,dict(type='register_event',event_id='e',user_id='a',role='lead'));same(s,again)
 denied(s,dict(type='override_role',event_id='e',organizer_id='other',user_id='a',role='follow'))
 s=ok(s,dict(type='override_role',event_id='e',organizer_id='org',user_id='b',role='follow'));assert {x['user_id']:x['role'] for x in s['events']['e']['attendees']}=={'a':'lead','b':'follow'};assert not s['events']['e']['waitlist']
 denied(s,dict(type='override_role',event_id='e',organizer_id='org',user_id='a',role='follow'))
 zero=register(event(lead=0),'a','lead');assert zero['registration_status']=='waitlisted'
 denied(s,dict(type='register_event',event_id='e',user_id='missing',role='lead'))
 output=rows(cli(event(),[{'command':'act','value':dict(type='register_event',event_id='e',user_id='a',role='lead')},{'command':'show'}]));assert any(x['user_id']=='a' for x in output[2]['events']['e']['attendees'])

def test_ru_004_matching_chat():
 s=ok(base(),dict(type='express_interest',user_id='a',target_id='b'));assert not any(x.get('active') for x in s['matches'].values());denied(s,dict(type='send_message',sender_id='a',recipient_id='b',text='hello'));denied(s,dict(type='express_interest',user_id='a',target_id='a'))
 s=ok(s,dict(type='express_interest',user_id='b',target_id='a'));s=ok(s,dict(type='express_interest',user_id='b',target_id='a'));active=[x for x in s['matches'].values() if x.get('active')];assert len(active)==1 and set(active[0]['users'])=={'a','b'}
 assert len(matches(s,'a'))==len(matches(s,'b'))==1 and not matches(s,'org')
 sent=ok(s,dict(type='send_message',sender_id='a',recipient_id='b',text='hello'));assert len(sent['messages'])==1 and all(sent['messages'][0][k]==v for k,v in {'sender_id':'a','recipient_id':'b','text':'hello'}.items())
 denied(sent,dict(type='send_message',sender_id='a',recipient_id='b',text=''));denied(sent,dict(type='send_message',sender_id='org',recipient_id='a',text='hello'))
 output=rows(cli(s,[{'command':'act','value':dict(type='send_message',sender_id='b',recipient_id='a',text='persisted')},{'command':'show'}]));assert output[2]['messages'][-1]['text']=='persisted'

def test_ru_005_block_report():
 s=matched();s=matched(s,'org','other');blocked=ok(s,dict(type='block',user_id='a',target_id='b'));replay=ok(blocked,dict(type='block',user_id='a',target_id='b'));same(blocked,replay)
 for a,b in [('a','b'),('b','a')]:
  assert not matches(blocked,a);denied(blocked,dict(type='send_message',sender_id=a,recipient_id=b,text='blocked'))
  # Blocking specifies effects, not whether a harmless interest no-op returns an error.
  out=call(blocked,dict(type='express_interest',user_id=a,target_id=b));private(out);same(blocked,out)
  if 'error' in out:assert out['error'].get('code')
  else:assert 'result' in out
  for key,value in clean(blocked).items():assert clean(out).get(key)==value,key
  assert not any(m.get('active') and set(m['users'])=={a,b} for m in out['matches'].values())
  assert not matches(out,a) and not matches(out,b)
  denied(out,dict(type='send_message',sender_id=a,recipient_id=b,text='still blocked'))
 assert len(matches(blocked,'org'))==1
 report=ok(blocked,dict(type='report',user_id='a',target_id='b',reason='harassment'));assert len(report['reports'])==len(report['admin_alerts'])==1
 for entry in [report['reports'][0],report['admin_alerts'][0]]:assert all(entry[k]==v for k,v in {'reporter_id':'a','target_id':'b','reason':'harassment'}.items())
 denied(blocked,dict(type='report',user_id='a',target_id='missing',reason='x'));denied(blocked,dict(type='report',user_id='a',target_id='b',reason=''))
 reflected=ok(base(),dict(type='report',user_id='a',target_id='b',reason='includes '+SECRETS[1]));private(reflected)
 output=rows(cli(s,[{'command':'act','value':dict(type='block',user_id='a',target_id='b')},{'command':'act','value':dict(type='send_message',sender_id='b',recipient_id='a',text='denied')},{'command':'show'}]));assert output[2]['error']['code'];assert not output[3]['messages']


def test_ru_003_revoked_organizer_cannot_override():
 s=register(event(),'a','lead')
 s['users']['org']['approved_organizer']=False
 denied(s,dict(type='override_role',event_id='e',organizer_id='org',user_id='a',role='follow'))


def test_ru_005_invalid_block_and_report_preserve_state():
 s=matched()
 for kind in ['block','report']:
  for user,target in [('a','a'),('missing','b'),('a','missing')]:
   denied(s,dict(type=kind,user_id=user,target_id=target,reason='synthetic reason'))
