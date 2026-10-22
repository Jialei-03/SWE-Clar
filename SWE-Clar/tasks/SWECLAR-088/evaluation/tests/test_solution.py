from copy import deepcopy
import hashlib,json
from candidate_proxy import call,cli

def base():return {'admins':['admin']}
def purchase(**values):return {'type':'purchase','event_id':'event','license_id':'license','license_key':'SYNTHETIC-KEY-1234','email':' User@Example.test ','shop':' Store.Example.test ','paid':True,**values}
def bought():return call(base(),purchase())
def verify(**values):return {'type':'verify','license_key':'SYNTHETIC-KEY-1234','shop':' STORE.EXAMPLE.TEST ','ip':' 192.0.2.1 ','timestamp':1,**values}
def unchanged(s,a):
 out=call(s,a);assert out.get('error')
 for k,v in s.items():
  if k not in ('result','error'):assert out.get(k)==v
 return out

def test_ru_001_entry_persistence_and_public_redaction():
 out=call(base(),purchase());assert out['result']['license_id']=='license' and out['licenses']['license']['shop']=='store.example.test'
 rows=cli(base(),[{'command':'act','value':purchase()},{'command':'show'},{'command':'act','value':purchase(event_id='bad',paid=False)},{'command':'show'},{'command':'init','value':{}}]);assert all(r['returncode']==0 for r in rows)
 assert rows[1]['output']['result']['license_id']=='license' and purchase()['license_key'] not in json.dumps(rows[1]['output'])
 assert rows[2]['output']['licenses']['license']['shop']=='store.example.test' and rows[3]['output'].get('error') and rows[4]['output']==rows[2]['output'] and rows[5]['output'].get('error')
 unchanged(base(),{'type':'unknown'})
 denied=cli(base(),[{'command':'act','value':purchase()},{'command':'show','value':{'admin_id':'outsider'}},{'command':'show'}])
 assert denied[2]['output'].get('error',{}).get('code')
 assert denied[3]['output']['licenses']['license']['shop']=='store.example.test'

def test_ru_002_purchase_delivery_and_replay_conflicts():
 s=bought();row=s['licenses']['license'];assert row['email']=='user@example.test' and row['status']=='active' and row['key_hash']==hashlib.sha256(purchase()['license_key'].encode()).hexdigest()
 assert 'license_key' not in row and len(s['deliveries'])==1;delivery=s['deliveries'][0];assert delivery['email']=='user@example.test' and delivery['status']=='queued' and purchase()['license_key'] in delivery['body']
 replay=call(s,purchase(license_id='other'));assert replay['result']['license_id']=='license' and replay['licenses']==s['licenses'] and replay['deliveries']==s['deliveries']
 for patch in [{'email':'other@example.test'},{'shop':'different.test'},{'license_key':'DIFFERENT-KEY-5678'},{'paid':False}]:unchanged(s,purchase(**patch))
 for patch in [{'paid':1},{'license_key':'tiny'},{'email':'missing-at'},{'shop':''}]:unchanged(base(),purchase(**patch))
 rows=cli(base(),[{'command':'act','value':purchase()},{'command':'act','value':purchase(license_id='other')},{'command':'show'}]);assert len(rows[-1]['output']['licenses'])==len(rows[-1]['output']['deliveries'])==1

def test_ru_003_bound_verification_status_and_ping():
 s=bought();out=call(s,verify());r=out['result'];assert r['valid'] is True and r['license_id']=='license' and r['key_suffix']=='1234' and 'key_hash' not in r and purchase()['license_key'] not in json.dumps(r)
 ping=out['pings'][0];assert all(ping[k]==v for k,v in {'license_id':'license','shop':'store.example.test','ip':'192.0.2.1','timestamp':1}.items())
 for patch in [{'license_key':'UNKNOWN-KEY'},{'ip':''},{'timestamp':True},{'timestamp':-1}]:unchanged(s,verify(**patch))
 for status in ['frozen','revoked']:
  changed=call(s,{'type':'set_status','admin_id':'admin','license_id':'license','status':status});unchanged(changed,verify())

def test_ru_004_secondary_use_audit_is_durable_and_deduplicated():
 s=bought();a=verify(shop=' Other.Example.test ');denied=call(s,a);assert denied.get('error') and len(denied['warnings'])==1 and denied['warnings'][0]['shop']=='other.example.test' and denied['warnings'][0]['status']=='frozen'
 replay=call(denied,verify(shop='OTHER.EXAMPLE.TEST'));assert replay['warnings']==denied['warnings'] and replay['licenses']==s['licenses'] and not replay.get('pings')
 assert call(replay,verify())['result']['valid'] is True
 rows=cli(base(),[{'command':'act','value':purchase()},{'command':'act','value':a},{'command':'act','value':a},{'command':'show'},{'command':'act','value':verify()},{'command':'show'}]);assert rows[2]['output'].get('error') and len(rows[4]['output']['warnings'])==1 and rows[5]['output']['result']['valid'] is True and len(rows[6]['output']['pings'])==1

def test_ru_005_trial_expiry_and_admin_search():
 search_controls()
 trial={'type':'trial','license_id':'trial','license_key':'SYNTHETIC-TRIAL-9999','email':'trial@example.test','shop':'trial.example.test','now':2,'expires_at':10};s=call(base(),trial)
 a=verify(license_key=trial['license_key'],shop=trial['shop'],now=9.99);assert call(s,a)['result']['valid'] is True
 for now in [10,11,True]:unchanged(s,{**a,'now':now})
 active=call(s,{'type':'set_status','admin_id':'admin','license_id':'trial','status':'active'});unchanged(active,{**a,'now':10})
 for query in [' TRIAL ','@example.test','trial.example','']:
  rows=call(s,{'type':'search','admin_id':'admin','query':query})['result']['licenses'];assert len(rows)==1 and rows[0]['key_suffix']=='9999' and 'key_hash' not in rows[0] and trial['license_key'] not in json.dumps(rows)
 for a in [{'type':'search','admin_id':'outsider'},{'type':'set_status','admin_id':'outsider','license_id':'trial','status':'frozen'}]:unchanged(s,a)
 for expiry in [2,1,True]:unchanged(base(),{**trial,'expires_at':expiry})

def search_controls():
 s=base()
 fixtures=[('zeta','third@demo.test','orchard.test'),('middle','needle@demo.test','river.test'),('alpha','first@demo.test','needle.test')]
 for ident,email,shop in fixtures:
  s=call(s,{'type':'trial','license_id':ident,'license_key':'SYNTHETIC-'+ident,'email':email,'shop':shop,'now':0,'expires_at':20})
  assert 'error' not in s,s
 for query,expected in [('', ['alpha','middle','zeta']),('does-not-exist',[]),(' ZETA ',['zeta']),('NEEDLE@',['middle']),('needle.test',['alpha']),('needle',['alpha','middle'])]:
  rows=call(s,{'type':'search','admin_id':'admin','query':query})['result']['licenses']
  assert [r['license_id'] for r in rows]==expected
  for row in rows:
   ident=row['license_id'];email,shop=next((email,shop) for key,email,shop in fixtures if key==ident)
   assert all(row.get(k)==v for k,v in {'email':email,'shop':shop,'status':'trial','key_suffix':('SYNTHETIC-'+ident)[-4:],'expires_at':20}.items())
   assert 'key_hash' not in row and 'SYNTHETIC-' not in json.dumps(row)
