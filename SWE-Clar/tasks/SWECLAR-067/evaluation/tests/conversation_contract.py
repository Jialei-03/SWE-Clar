"""Independent real-browser/HTTP oracles for the five frozen requirements."""
import json,os,secrets,select,subprocess,sys,tempfile,threading,time,traceback
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace')).resolve();BROWSER=None
os.environ['CLARSWE_PRIVATE_BROWSER_SENTINEL']=secrets.token_hex(24)
class Fixture:
 def __init__(self,chat=False):
  self.temp=tempfile.TemporaryDirectory(prefix='conversation-case-');self.root=Path(self.temp.name);self.root.chmod(0o755);self.config_path=self.root/'server.json';self.records=[]
  suffix=secrets.token_hex(4);self.first='first-'+suffix;self.second='second-'+suffix
  self.chat_route='/conversation-'+suffix;self.schedule='/appointment-'+suffix+'?slot=demo'
  self.seed={'conversations':{self.first:{'title':'First synthetic conversation','transcript':['A saved synthetic sentence.','<img src=x onerror="window.injected=true">'],'pending_question':'Which example comes next?'},self.second:{'title':'Second synthetic conversation','transcript':['Another synthetic entry.'],'pending_question':'Continue the second example?'}},'routes':{'chat':self.chat_route+'?existing=keep','chat_prefill':'Hello & continue? + 测试','schedule':self.schedule},'report_endpoint':'/report-'+suffix,'view':{'screen':'chat','conversation_id':self.first} if chat else {'screen':'main'}}
  self.settings={'report_path':self.seed['report_endpoint'],'destinations':[self.chat_route,urlsplit(self.schedule).path]};self.configure()
  self.process=subprocess.Popen([sys.executable,'-I','/public_tests/serve.py','--project',str(ROOT),'--port','0','--config',str(self.config_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
  assert select.select([self.process.stdout],[],[],5)[0],'Prepared fixture failed to start';ready=json.loads(self.process.stdout.readline());assert ready['uid']==1000 and ready['cap_eff']==0 and set(ready['environment_keys']) <= {'HOME','PATH','LC_CTYPE'},ready
  self.base='http://127.0.0.1:'+str(ready['port']);self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start()
  self.context=BROWSER.new_context(viewport={'width':390,'height':850});self.context.add_init_script('window.ASSISTANT_DATA='+json.dumps(self.seed,ensure_ascii=False)+';');self.outside=[];self.errors=[]
  self.context.route('**/*',self.route);self.page=self.context.new_page();self.page.set_default_timeout(4000);self.page.on('pageerror',lambda error:self.errors.append(str(error)));self.page.goto(self.base)
 def route(self,route):
  if route.request.url.startswith(self.base+'/'):route.continue_()
  else:self.outside.append(route.request.url);route.abort()
 def read(self):
  for line in self.process.stdout:
   try:self.records.append(json.loads(line))
   except ValueError:pass
 def configure(self,**changes):
  self.settings.update(changes);self.config_path.write_text(json.dumps(self.settings));self.config_path.chmod(0o644)
 def send(self,event):return self.page.evaluate('(event)=>window.assistantApp.dispatch(event)',event)
 def snapshot(self):return self.page.evaluate('window.assistantApp.snapshot()')
 def reports(self):return [r for r in self.records if r.get('method')=='POST']
 def wait(self,predicate):
  until=time.monotonic()+5
  while time.monotonic()<until:
   if predicate():return
   self.page.wait_for_timeout(10)
  raise AssertionError('Expected HTTP record not observed')
 def __enter__(self):return self
 def __exit__(self,kind,*rest):
  self.context.close();self.process.terminate();self.process.wait(timeout=5);self.reader.join(timeout=1);self.temp.cleanup()
  if kind is None:assert not self.outside and not self.errors,(self.outside,self.errors)

def ru1():
 with Fixture(chat=True) as a:
  assert a.page.locator('#transcript').inner_text() and a.page.locator('#transcript img').count()==0 and not a.page.evaluate('window.injected || false')
  assert a.page.locator('#transcript p').all_text_contents()==a.seed['conversations'][a.first]['transcript']
  assert a.page.evaluate('window.ASSISTANT_DATA')==a.seed
  assert a.page.evaluate('''async()=>{const event={type:'show_page',page:'clinic'},before=JSON.stringify(event);await window.assistantApp.dispatch(event);const copy=window.assistantApp.snapshot();copy.conversations[Object.keys(copy.conversations)[0]].transcript.push('changed');copy.routes.chat='changed';const current=window.assistantApp.snapshot();return JSON.stringify(event)===before&&current.routes.chat!=='changed'&&!current.conversations[Object.keys(current.conversations)[0]].transcript.includes('changed')}''')
  assert a.page.locator('#clinic').is_visible();a.page.get_by_role('button',name='Home',exact=True).click();assert a.page.locator('#home').is_visible()

def ru2():
 with Fixture() as a:
  a.page.get_by_role('button',name='First synthetic conversation',exact=True).click();assert a.page.locator('#chat').is_visible()
  assert a.page.locator('#transcript p').all_text_contents()==a.seed['conversations'][a.first]['transcript'];assert a.page.locator('#pending-question').inner_text()==a.seed['conversations'][a.first]['pending_question']
  a.page.reload();assert a.page.locator('#chat').is_visible();assert a.snapshot()['view']['conversation_id']==a.first
  before=a.snapshot()['view'];out=a.send({'type':'open_chat','conversation_id':'absent'});assert out['error']['code']=='unknown_conversation' and out['view']==before
  a.send({'type':'open_chat','conversation_id':a.second});a.page.reload();assert a.page.locator('#pending-question').inner_text()==a.seed['conversations'][a.second]['pending_question'];assert a.page.locator('#transcript p').all_text_contents()==a.seed['conversations'][a.second]['transcript']

def ru3():
 with Fixture() as a:
  values=[' First sentence. ',' <script>literal</script> ','Unicode α and internal  spaces.'];out=a.send({'type':'format_tip','sentences':values});expected=[x.strip() for x in values]
  assert out['formatted_tip']=='\n\n'.join(expected);assert a.page.locator('#tips p').all_text_contents()==expected;assert a.page.locator('#tips script').count()==0
  bounds=a.page.locator('#tips p').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {top:r.top,bottom:r.bottom}})');assert all(b['top']>a['bottom'] for a,b in zip(bounds,bounds[1:]))
  for invalid in [None,[],['valid',' '],['valid',None],['valid',4],'not a list']:
   assert a.send({'type':'format_tip','sentences':invalid})['error']['code']=='invalid_tip'

def ru4():
 with Fixture() as a:
  for page,action in [('main','Schedule Demo'),('clinic','Chat with Assistant'),('other','Request a Demo'),('main','unknown')]:assert a.send({'type':'activate_cta','page':page,'action':action})['error']['code']=='unknown_cta'
  with a.page.expect_navigation():a.page.get_by_role('link',name='Chat with Assistant',exact=True).click()
  url=urlsplit(a.page.url);assert url.path==a.chat_route and parse_qs(url.query)=={'existing':['keep'],'text':[a.seed['routes']['chat_prefill']]};a.wait(lambda:any(r.get('path','').startswith(a.chat_route+'?') for r in a.records))
 for label in ['Schedule Demo','Request a Demo','Pre-Onboard Patients']:
  with Fixture() as a:
   a.page.get_by_role('button',name='Clinic',exact=True).click()
   with a.page.expect_navigation():a.page.get_by_role('link',name=label,exact=True).click()
   assert a.page.url==a.base+a.schedule;a.wait(lambda:any(r.get('path')==a.schedule for r in a.records))
 # Dispatch returns routing data. Actual navigation is checked through the
 # anchors above; the contract does not require dispatch itself to reload.
 for page,action in [('main','Chat with Assistant'),('clinic','Schedule Demo')]:
  with Fixture() as a:
   returned=a.send({'type':'activate_cta','page':page,'action':action})
   expected={'destination':a.seed['routes']['chat'],'prefill':a.seed['routes']['chat_prefill']} if page=='main' else {'destination':a.schedule}
   assert returned['navigation']==expected

def ru5():
 with Fixture(chat=True) as a:
  event={'type':'report_bug','conversation_id':a.first,'report_id':'report:'+a.first}
  for failure in [{'status':503},{'status':200,'ack_id':'different'},{'status':200,'ack_id':event['report_id'],'accepted':False}]:
   a.configure(**failure);out=a.send(event);assert out['error']['code']=='report_failed' and not out['bug_reports'];assert not a.page.locator('#acknowledgement').inner_text().strip()
  a.configure(status=200,ack_id=event['report_id'],accepted=True)
  a.page.get_by_role('button',name='Report bug',exact=True).click();a.page.wait_for_function('Object.keys(window.assistantApp.snapshot().bug_reports).length===1');assert a.page.locator('#acknowledgement').is_visible() and a.page.locator('#acknowledgement').inner_text().strip()
  report=a.reports()[-1];assert report['body']=={'report_id':event['report_id'],'conversation_id':a.first,'transcript':a.seed['conversations'][a.first]['transcript']};assert report['idempotency_key']==event['report_id'] and report['content_type'].split(';')[0]=='application/json'
  count=len(a.reports());a.page.reload();a.send(event);assert len(a.reports())==count
  concurrent={**event,'report_id':'concurrent-'+a.first};a.configure(delay_ms=220,ack_id=concurrent['report_id'])
  a.page.evaluate("event=>{window.deliveries=Promise.all([window.assistantApp.dispatch(event),window.assistantApp.dispatch(event)])}",concurrent)
  a.wait(lambda:len(a.reports())>count);a.send({'type':'show_page','page':'clinic'});a.page.evaluate('window.deliveries');assert a.page.locator('#clinic').is_visible() and len(a.reports())==count+1
  assert concurrent['report_id'] in a.snapshot()['bug_reports'];a.page.reload();assert a.page.locator('#clinic').is_visible()
  for user,day in [('synthetic-user',0),('synthetic-user',9),('synthetic-user',10),('another-user',10)]:a.send({'type':'feedback_tick','user_id':user,'day':day,'interval_days':10})
  assert a.page.locator('#feedback p').count()==3;a.page.reload();a.send({'type':'feedback_tick','user_id':'synthetic-user','day':10,'interval_days':10});assert a.page.locator('#feedback p').count()==3
  for values in [{'day':-1},{'day':1.5},{'interval_days':0},{'interval_days':True},{'user_id':''}]:
   out=a.send({'type':'feedback_tick','user_id':'synthetic-user','day':10,'interval_days':10,**values});assert out.get('error') and a.page.locator('#feedback p').count()==3

def main():
 global BROWSER
 if not all(Path('/public_tests',name).is_file() for name in ['serve.py','browser_launcher.py','browser_isolation.py']):return {'harness_ok':False,'results':[],'error':'Protected helper missing'}
 sys.path.insert(0,'/public_tests')
 try:
  from browser_isolation import launch
  from playwright.sync_api import sync_playwright
  playwright=sync_playwright().start();BROWSER=launch(playwright.chromium,headless=True)
 except Exception as error:return {'harness_ok':False,'results':[],'error':str(error)}
 rows=[]
 try:
  for i,test in enumerate([ru1,ru2,ru3,ru4,ru5],1):
   try:test();rows.append({'ru_id':f'RU-{i:03}','passed':True})
   except Exception as error:rows.append({'ru_id':f'RU-{i:03}','passed':False,'detail':str(error) or type(error).__name__,'trace':traceback.format_exc()[-2200:]})
 finally:BROWSER.close();playwright.stop()
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':
 result=main();print(json.dumps(result));sys.exit(2 if not result['harness_ok'] else int(any(not r['passed'] for r in result['results'])))
