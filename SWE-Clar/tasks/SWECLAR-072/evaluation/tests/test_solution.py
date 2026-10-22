from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json,os,secrets,subprocess,sys,tempfile
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.'));WHITE={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
os.environ['BACKEND_PRIVATE_SENTINEL']=secrets.token_hex(24)
def call(state,command):
 p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'state':state,'command':command}),text=True,capture_output=True,timeout=15,user=1000,group=1000,extra_groups=[],env=WHITE,cwd=ROOT);assert p.returncode==0,p.stderr[-300:];out=json.loads(p.stdout);assert out['state_after']==state and out['command_after']==command;assert isinstance(out['result'],dict);return out['result']
def refund(key='k',amount=5.5,**changes):return {'type':'refund','idempotency_key':key,'order_id':'order','amount':amount,'currency':'usd',**changes}
def comment(ident,parent=None,at=1):
 # parent_id is optional; when present it is a nonempty identifier. The
 # contract does not require accepting JSON null as an identifier.
 return {'type':'comment','id':ident,'body':'Synthetic '+ident,'created_at':at,**({'parent_id':parent} if parent is not None else {})}
def request(now,email=' User@Example.test '):return {'type':'passwordless','email':email,'now':now}
def ok(out):assert 'error' not in out,out.get('error');return out
def rejection(out):assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
def view(state):return {k:state.get(k) for k in ['refunds','comments','login_attempts'] if k in state}
def duplicate_comment(before,after):
 # Unique insertion IDs permit rejection or a no-op retry, not overwrite/append.
 if 'error' in after:rejection(after)
 assert after['comments']==before['comments']
 assert len({r['id'] for r in after['comments']})==len(after['comments'])
class Durable:
 def __init__(self,seed=None):self.seed={} if seed is None else seed
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.root.chmod(0o777);self.db=self.root/'commands.sqlite';self.run('init',self.seed);return self
 def __exit__(self,*args):self.tmp.cleanup()
 def run(self,mode,value=None):
  p=subprocess.run([sys.executable,str(ROOT/'cli.py'),str(self.db),mode],input=json.dumps(value) if value is not None else None,text=True,capture_output=True,timeout=30,cwd=ROOT,user=1000,group=1000,extra_groups=[],env=WHITE);assert p.returncode==0,p.stderr[-300:];return json.loads(p.stdout)
 def apply(self,value):return self.run('apply',value)

def test_ru_001_copy_and_persistence():
 seed={'extra':{'nested':[1,2]}};out=ok(call(seed,refund()));assert out['extra']==seed['extra']
 with Durable(seed) as d:
  result=ok(d.apply(refund()));saved=d.run('snapshot');assert saved['refunds']==result['refunds'] and saved['extra']==seed['extra'];assert d.db.read_bytes().startswith(b'SQLite format 3\0')

def test_ru_002_pending_refund_validation():
 out=ok(call({},refund()));assert out['refunds']==[{'idempotency_key':'k','order_id':'order','amount':5.5,'currency':'USD','status':'pending'}]
 for changes in [{'idempotency_key':''},{'order_id':''},{'currency':''},{'amount':0},{'amount':-1},{'amount':True},{'amount':'5'}]:
  bad=call(out,refund(key='new',**changes));rejection(bad);assert bad['refunds']==out['refunds']


def test_ru_003_old_key_replay_and_concurrency():
 one=ok(call({},refund()));two=ok(call(one,refund('second',8)));again=ok(call(two,refund('k',amount=99,order_id='changed',currency='EUR')))
 assert again['refunds']==two['refunds'] and view(again)==view(two);assert again['refund_result']==one['refunds'][0]
 with Durable() as d:
  with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(lambda _:d.apply(refund()),range(5)))
  assert all('error' not in r for r in results);ok(d.apply(refund('second',8)));before=d.run('snapshot');replay=ok(d.apply(refund()));after=d.run('snapshot');assert before['refunds']==after['refunds'] and len(after['refunds'])==2 and view(after)==view(before);assert replay['refund_result']==results[0]['refund_result']

def test_ru_004_comments_order_missing_parent_cycle():
 state={}
 for ident,parent,at in [('root',None,30),('child','root',10),('grandchild','child',0)]:state=ok(call(state,comment(ident,parent,at)))
 assert [r['id'] for r in state['comments']]==['root','child','grandchild'];assert state['comments'][2]['parent_id']=='child'
 for ident,parent in [('root',None),('child',None),('child','root')]:duplicate_comment(state,call(state,{**comment(ident,parent,99),'body':'Changed duplicate'}))
 bad=call(state,comment('other','absent'));assert bad['error']['code']=='missing_parent' and bad['comments']==state['comments']
 seed={'comments':[{'id':'a','parent_id':'b','body':'imported','created_at':1}]};bad=call(seed,comment('b','a'));assert bad['error']['code']=='comment_cycle' and bad['comments']==seed['comments']
 selfcycle=call({},comment('self','self'));assert selfcycle['error']['code']=='comment_cycle'
 with Durable() as d:
  for ident,parent,at in [('root',None,30),('child','root',10),('grandchild','child',0)]:ok(d.apply(comment(ident,parent,at)))
  stored=d.run('snapshot');assert [r['id'] for r in stored['comments']]==['root','child','grandchild'];bad=d.apply(comment('other','absent'));assert bad['error']['code']=='missing_parent' and d.run('snapshot')['comments']==stored['comments']
  for ident,parent in [('root',None),('child',None),('child','root')]:
   duplicate_comment(stored,d.apply({**comment(ident,parent,99),'body':'Changed duplicate'}));duplicate_comment(stored,d.run('snapshot'))

def test_ru_005_rolling_limiter_and_atomic_acceptance():
 state={}
 for now in [0,10,20]:state=ok(call(state,request(now)));assert state['login_result']=={'accepted':True}
 limited=ok(call(state,request(30,'user@example.test')));assert limited['login_result']=={'accepted':False,'retry_after_seconds':870}
 near=ok(call(limited,request(899)));assert near['login_result']=={'accepted':False,'retry_after_seconds':1}
 edge=ok(call(near,request(900)));assert edge['login_result']=={'accepted':True}
 blocked=ok(call(edge,request(901)));assert blocked['login_result']=={'accepted':False,'retry_after_seconds':9}
 assert ok(call(blocked,request(901,'another@example.test')))['login_result']=={'accepted':True}
 fractional={}
 for when in [0.5,10.5,20.5]:fractional=ok(call(fractional,request(when)))
 assert ok(call(fractional,request(30.25)))['login_result']=={'accepted':False,'retry_after_seconds':870.25}
 with Durable() as d:
  with ThreadPoolExecutor(max_workers=6) as pool:out=list(pool.map(lambda _:d.apply(request(100)),range(6)))
  assert sum(x['login_result']['accepted'] for x in out)==3
  assert ok(d.apply(request(101)))['login_result']=={'accepted':False,'retry_after_seconds':899}
  assert ok(d.apply(request(1000)))['login_result']=={'accepted':True}
