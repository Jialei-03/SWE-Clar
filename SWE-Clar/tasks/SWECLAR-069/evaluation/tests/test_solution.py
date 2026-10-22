from pathlib import Path
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json,os,secrets,subprocess,sys,tempfile
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.'));WHITE={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
os.environ['CREDITS_PRIVATE_SENTINEL']=secrets.token_hex(24)
def call(state,action):
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'state':state,'action':action}),text=True,capture_output=True,timeout=15,user=1000,group=1000,extra_groups=[],env=WHITE,cwd=ROOT);assert p.returncode==0,p.stderr[-300:];r=json.loads(p.stdout);assert r['state_after']==state and r['action_after']==action;assert isinstance(r['result'],dict);return r['result']
def base():return {'users':{},'jobs':{**{f'j{i}':{'category':'roofing','credit_cost':1} for i in range(1,8)},'other':{'category':'plumbing','credit_cost':2}},'ledger':[],'processed_ids':[]}
def user(uid='u',categories=None,role='contractor'):return {'type':'create_user','user_id':uid,'categories':['roofing'] if categories is None else categories,'role':role}
def grant(ident='pay',uid='u',amount=10,period='monthly'):return {'type':'subscribe','user_id':uid,'payment_id':ident,'credit_grant':amount,'period':period}
def unlock(job='j1',ident='e1',uid='u'):return {'type':'unlock_job','user_id':uid,'job_id':job,'event_id':ident}
def funded(amount=10,categories=None):return ok(call(ok(call(base(),user(categories=categories))),grant(amount=amount)))
def ok(result):assert 'error' not in result,result.get('error');return result
def entries(state):return [{k:v for k,v in row.items() if k in ['event_id','user_id','delta','kind','period','job_id']} for row in state['ledger']]
def denied(before,action):
 out=call(before,action);assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code'];assert entries(out)==entries(before)
 for uid,u in before['users'].items():assert out['users'][uid]['credits']==u['credits']
 return out
class Durable:
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.root.chmod(0o777);self.db=self.root/'ledger.sqlite';self.run('init',base());return self
 def __exit__(self,*args):self.tmp.cleanup()
 def run(self,mode,value=None):
  p=subprocess.run([sys.executable,str(ROOT/'cli.py'),str(self.db),mode],input=json.dumps(value) if value is not None else None,text=True,capture_output=True,timeout=30,cwd=ROOT,user=1000,group=1000,extra_groups=[],env=WHITE);assert p.returncode==0,p.stderr[-300:];return json.loads(p.stdout)
 def apply(self,action):return self.run('apply',action)

def test_ru_001_inputs_and_real_persistence():
 seed=base();seed['extra']={'nested':[1,2]};r=ok(call(seed,user()));assert r['extra']==seed['extra'] and 'u' in r['users']
 with Durable() as d:
  ok(d.apply(user()));state=d.run('snapshot');assert state['users']['u']['role']=='contractor' and state['users']['u']['credits']==0
  assert d.db.read_bytes().startswith(b'SQLite format 3\0')

def test_ru_002_roles_and_categories():
 for role in ['contractor','supplier']:
  r=ok(call(base(),user(role=role,categories=['a','b','c','d','e'])));assert r['users']['u']['role']==role and r['users']['u']['categories']==['a','b','c','d','e']
 for categories in [[],['a']*2,list('abcdef'),[''],[1],[['x']]]:denied(base(),user(categories=categories))
 denied(base(),user(role='admin'));state=ok(call(base(),user()));denied(state,user())

def test_ru_003_credit_grants_and_replay():
 for period in ['monthly','quarterly','yearly']:
  state=ok(call(base(),user()));event=grant(period=period);one=ok(call(state,event));assert one['users']['u']['credits']==10 and len(one['ledger'])==1
  row=entries(one)[0];assert all(row[k]==v for k,v in {'event_id':'pay','user_id':'u','delta':10,'kind':'credit_grant','period':period}.items())
  replay=ok(call(one,event));assert replay['result']['replayed'] is True and replay['users']['u']['credits']==10 and entries(replay)==entries(one)
  assert 'tokens' not in replay['users']['u'] and 'token' not in replay['users']['u']
  denied(one,grant(amount=11,period=period))
 for amount in [True,0,-1,1.5,'10']:denied(ok(call(base(),user())),grant(amount=amount))
 denied(ok(call(base(),user())),grant(period='weekly'))
 with Durable() as d:
  ok(d.apply(user()));one=ok(d.apply(grant()));replay=ok(d.apply(grant()));assert replay['result']['replayed'] and d.run('snapshot')['users']['u']['credits']==10 and len(d.run('snapshot')['ledger'])==1

def test_ru_004_quota_balance_and_atomic_competition():
 state=funded();denied(state,unlock('other'));invalid=deepcopy(state);invalid['jobs']['j1']['credit_cost']=True;denied(invalid,unlock())
 poor=funded(amount=1,categories=['roofing','plumbing']);denied(poor,unlock('other'))
 with Durable() as d:
  ok(d.apply(user(categories=['roofing','plumbing'])));ok(d.apply(grant(amount=20)))
  with ThreadPoolExecutor(max_workers=7) as pool:out=list(pool.map(lambda i:d.apply(unlock('j'+str(i),'e'+str(i))),range(1,8)))
  assert sum('error' not in x for x in out)==5
  state=d.run('snapshot');assert state['users']['u']['credits']==15 and len(state['ledger'])==6
  ok(d.apply(unlock('other','other-event')));assert d.run('snapshot')['users']['u']['credits']==13
  ok(d.apply(user(uid='v')));ok(d.apply(grant('pay-v',uid='v')));ok(d.apply(unlock('j1','v-job',uid='v')));assert d.run('snapshot')['users']['v']['credits']==9

def test_ru_005_immutable_events_and_failed_later_unlock():
 state=funded(amount=2);one=ok(call(state,unlock()));assert one['users']['u']['credits']==1
 assert all(entries(one)[-1][k]==v for k,v in {'event_id':'e1','user_id':'u','delta':-1,'kind':'job_unlock','job_id':'j1'}.items())
 replay=ok(call(one,unlock()));assert replay['result']['replayed'] is True and entries(replay)==entries(one)
 denied(one,unlock('j2','e1'));denied(one,unlock('j1','new-id'));denied(one,grant('e1'));denied(one,unlock('j2','pay'))
 changed=deepcopy(one);changed['jobs']['j2']['credit_cost']=2;denied(changed,unlock('j2','e2'))
 with Durable() as d:
  ok(d.apply(user()));ok(d.apply(grant(amount=2)))
  with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:d.apply(unlock()),range(4)))
  assert all('error' not in x for x in results);saved=d.run('snapshot');assert saved['users']['u']['credits']==1 and len(saved['ledger'])==2
  failed=d.apply(unlock('other','bad'));assert 'error' in failed;after=d.run('snapshot');assert after['users']['u']['credits']==1 and entries(after)==entries(saved)
  conflict=d.apply(unlock('j2','e1'));assert 'error' in conflict and entries(d.run('snapshot'))==entries(saved)
