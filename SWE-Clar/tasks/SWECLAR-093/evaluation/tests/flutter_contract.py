"""Protected business expectations over public real Flutter/network observations."""
import os,sys,json,tempfile,subprocess,select,shutil,time,re
from pathlib import Path
sys.path.insert(0,'/public_tests')
from shop_support import run_session,CandidateFailure

def visible_value(texts,label,value,unit=''):
 text=' '.join(x for x in texts if isinstance(x,str));text=re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','',text)
 pattern=rf'\b{re.escape(label)}\b\s*[:=\-–—]?\s*{value}(?![\d.])'
 if unit:pattern+=rf'\s*{unit}\b'
 assert re.search(pattern,text,re.I),(label,value,text)

def visible_quantity(texts,product,quantity):
 text=' '.join(x for x in texts if isinstance(x,str))
 forward=rf'\b{re.escape(product)}\b\s*(?:[×x*]|[\-–—,:]?\s*(?:quantity|qty)\s*[:=]?)\s*{quantity}(?![\d.])'
 reverse=rf'(?<![\d.]){quantity}\s*[×x*]\s*{re.escape(product)}\b'
 assert re.search(forward+'|'+reverse,text,re.I),text

def structured_failure(row):
 assert 400<=row['status']<600,row
 body=row['body'];assert isinstance(body,dict) and body.get('error'),row
 assert isinstance(body['error'],(str,dict)),row

def main():
 os.environ['SHOP_PRIVATE_SENTINEL']='private-grading-context'
 for file in ['shop_driver_test.dart','wire_observer.cjs']:
  if not Path('/public_tests',file).is_file():return {'harness_ok':False,'results':[],'error':'Missing public operation worker'}
 root=Path(tempfile.mkdtemp(prefix='shop-backend-'));root.chmod(0o777)
 config={'users':{'one':{'role':'mobile'},'two':{'role':'mobile'},'manager':{'role':'manager'}},'sessions':{'token-one':'one','token-two':'two','token-manager':'manager'},'products':{'item':{'title':'Sample item','price_cents':250},'second':{'title':'Second item','price_cents':125}}}
 (root/'config.json').write_text(json.dumps(config));env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'SHOP_CONFIG':str(root/'config.json'),'PORT':'0','SWECLAR_NODE_REQUIRE_ROOT':'/opt/sweclar/websocket/package.json','SHOP_TRACE':str(root/'trace.jsonl'),'SHOP_PROCESS_PROOF':str(root/'process.json'),'NODE_OPTIONS':'--require /public_tests/wire_observer.cjs'}
 log=(root/'stderr.log').open('w');p=None
 try:
  p=subprocess.Popen(['node','server/server.cjs'],cwd=os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),env=env,user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=log,text=True)
  try:
   if not select.select([p.stdout],[],[],10)[0]:raise ValueError('Backend startup timed out')
   port=json.loads(p.stdout.readline())['port']
  except (ValueError,KeyError) as e:raise CandidateFailure('Candidate backend did not announce a local port: '+str(e)) from e
  base=f'http://127.0.0.1:{port}'
  ops=[];index={}
  def add(label,op,**fields):index[label]=len(ops);ops.append({'op':op,**fields})
  def action(label,name='one',**value):add(label,'action',name=name,value=value)
  def get(label,name='one',resource='cart'):add(label,'get',name=name,resource=resource)
  def publish(label,id,channel='updates',title='Live arrival'):action(label,'manager',type='publish',id=id,channel=channel,title=title)
  for name,token in [('one','token-one'),('again','token-one'),('two','token-two'),('manager','token-manager'),('ui','token-one'),('invalid','unknown')]:add('client-'+name,'client',name=name,base=base,token=token)
  for name in ['one','again','two']:add('socket-'+name,'connect',name=name)
  add('loaded','load',name='ui');add('screen','mount')
  add('subscribe-ui','tap',key='subscribe');action('subscribe-replay',type='subscribe',channel='updates');action('other-channel',type='subscribe',channel='other');action('second-user','two',type='subscribe',channel='other')
  publish('first-publish','live');add('live-arrived','wait',ms=200);publish('replay','live');add('replay-wait','wait',ms=200)
  action('conflict','manager',type='publish',id='live',channel='updates',title='Changed');action('not-manager',type='publish',id='denied',channel='updates',title='Denied')
  add('unsubscribe-ui','tap',key='unsubscribe');publish('not-delivered','later');publish('other-publish','other-id','other','Other message');add('settled','wait',ms=1100)
  get('inbox-one',resource='inbox');get('inbox-two','two','inbox')
  add('quantity','enter',key='quantity',text='2');add('cart-first','tap',key='add-item');action('merged',type='add',product_id='item',quantity=3,price_cents=0,user_id='two');action('removed',type='remove',product_id='item',quantity=2)
  # Reload cart through a real UI request, preserving the existing UI instance.
  add('cart-rendered','tap',key='add-item');add('invalid-quantity','enter',key='quantity',text='0');add('cart-failed','tap',key='add-item')
  for i,value in enumerate([True,0,-1,1.5,9007199254740992]):action('badqty-'+str(i),type='add',product_id='item',quantity=value)
  action('overflow',type='add',product_id='item',quantity=9007199254740991)
  action('missing-product',type='add',product_id='absent',quantity=1);action('empty-channel',type='subscribe',channel=' ');action('unknown-action',type='unsupported');get('preserved');get('other-cart','two')
  get('bad-auth','invalid');add('bad-socket','connect',name='invalid')
  # Independently inspect responses; a candidate JSON decoder exception is not an error envelope.
  raw_errors=[]
  for invalid_label in ['badqty-'+str(i) for i in range(5)]+['overflow','missing-product','empty-channel','unknown-action']:
   prior=ops[index[invalid_label]];label='raw-'+invalid_label;raw_errors.append(label);add(label,'http',name=prior['name'],path='/actions',value=prior['value'])
  raw_errors.append('raw-auth');add('raw-auth','http',name='invalid',method='GET',path='/cart')
  get('raw-preserved');get('raw-inbox',resource='inbox')
  action('zeroed',type='remove',product_id='item',quantity=999);get('empty-cart')
  add('receive-copy','receive',value={'id':'copy','channel':'local','title':'Original'});add('mutated','mutate_original',value={'title':'Changed'});add('duplicate-stream','receive',value={'id':'copy','channel':'local','title':'Original'})
  add('capture','capture',name='shop.png')
  result=run_session(ops);rows=result['observations'];trace=[json.loads(line) for line in (root/'trace.jsonl').read_text().splitlines()];proof=json.loads((root/'process.json').read_text())
  assert proof['uid']==1000 and int(next(x.split()[1] for x in proof['status'].splitlines() if x.startswith('CapEff:')),16)==0
  assert set(proof['environment_keys'])==set(env) and 'SHOP_PRIVATE_SENTINEL' not in proof['environment_keys']
  flutter=result['process'];status=flutter['status'];assert next(x.split()[1:] for x in status.splitlines() if x.startswith('Uid:'))==['1000']*4
  assert int(next(x.split()[1] for x in status.splitlines() if x.startswith('CapEff:')),16)==0 and 'SHOP_PRIVATE_SENTINEL' not in flutter['environment_keys']
  def r(label):return rows[index[label]]
  def ok(label):assert not r(label).get('operation_error') and not r(label).get('render_errors'),r(label).get('operation_error') or r(label).get('render_errors')
  def ids(values):return [v['id'] for v in values]
  def err(label):assert isinstance(r(label).get('operation_error'),str) and r(label)['operation_error']
  def cart(label,count):
   v=r(label)['result'];assert v['total_cents']==count*250;lines=v['lines'];assert len(lines)==(1 if count else 0)
   if count:assert all(lines[0].get(k)==value for k,value in {'product_id':'item','quantity':count,'price_cents':250,'line_total_cents':count*250}.items())
  def check1():
   ok('loaded');ok('screen');assert r('loaded')['loaded'] and r('loaded')['basket']['total_cents']==0
   assert 'Sample item' in r('screen')['texts'];assert any(x['event']=='upgrade' and x['path']=='/events' for x in trace)
   assert next(x for x in r('mutated')['messages'] if x['id']=='copy')['title']=='Original'
   assert sum(x['id']=='copy' for x in r('duplicate-stream')['messages'])==1
  def check2():
   for n in ['subscribe-ui','subscribe-replay','other-channel','second-user','unsubscribe-ui']:ok(n)
   assert ids(r('inbox-one')['result'])==['live','other-id'];assert ids(r('inbox-two')['result'])==['other-id']
  def check3():
   for n in ['first-publish','live-arrived','replay','replay-wait']:ok(n)
   for client in ['one','again']:assert ids(r('live-arrived')['received'][client])==['live'];assert ids(r('replay-wait')['received'][client])==['live']
   assert r('live-arrived')['received']['two']==[] and 'Live arrival' in ' '.join(r('live-arrived')['texts']);visible_value(r('live-arrived')['texts'],'Unread',1)
   err('conflict');err('not-manager')
   assert not [x for x in trace if x['event']=='request' and x['method']=='GET' and x['path']=='/inbox' and r('first-publish')['time_ms']<=x['time_ms']<r('settled')['time_ms']], 'Polling during unsolicited delivery window'
  def check4():
   ok('cart-first');visible_value(r('cart-first')['texts'],'Total',500,'cents');cart('merged',5);cart('removed',3)
   ok('cart-rendered');visible_value(r('cart-rendered')['texts'],'Total',1250,'cents');visible_quantity(r('cart-rendered')['texts'],'item',5);cart('other-cart',0);cart('zeroed',0);cart('empty-cart',0)
  def check5():
   for label in raw_errors:structured_failure(r(label)['http'])
   assert r('raw-preserved')['result']==r('preserved')['result'] and r('raw-inbox')['result']==r('inbox-one')['result']
   for n in ['badqty-'+str(i) for i in range(5)]+['overflow','missing-product','empty-channel','unknown-action','bad-auth','bad-socket']:err(n)
   assert isinstance(r('cart-failed')['error'],str) and r('cart-failed')['error'];assert r('cart-failed')['basket']['total_cents']==r('cart-rendered')['basket']['total_cents'];assert [(v['product_id'],v['quantity'],v['line_total_cents']) for v in r('cart-failed')['basket']['lines']]==[(v['product_id'],v['quantity'],v['line_total_cents']) for v in r('cart-rendered')['basket']['lines']];assert r('preserved')['result']['total_cents']==r('cart-rendered')['basket']['total_cents'];assert [(v['product_id'],v['quantity']) for v in r('preserved')['result']['lines']]==[(v['product_id'],v['quantity']) for v in r('cart-rendered')['basket']['lines']]
  results=[]
  for i,check in enumerate([check1,check2,check3,check4,check5],1):
   try:check();passed,detail=True,'passed'
   except Exception as e:passed,detail=False,type(e).__name__+': '+str(e)
   results.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
  evidence=Path('/private/evidence')
  if evidence.is_dir():(evidence/'observations.json').write_text(json.dumps(result));(evidence/'wire.json').write_text(json.dumps(trace));(evidence/'server-process.json').write_text(json.dumps(proof))
  return {'harness_ok':True,'results':results}
 except CandidateFailure as e:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)[-2000:]} for i in range(1,6)]}
 finally:
  if p and p.poll() is None:p.terminate();p.wait(timeout=10)
  log.close();shutil.rmtree(root)
if __name__=='__main__':
 try:print(json.dumps(main()))
 except Exception as e:print(json.dumps({'harness_ok':False,'error':type(e).__name__+': '+str(e),'results':[]}))
