from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,threading,traceback,sqlite3
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
def drop():
 os.setgroups([]);os.setgid(1000);os.setuid(1000)
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
class HarnessUnavailable(RuntimeError):pass
class Bridge:
 def __enter__(self):
  self.calls=[];self.bad=False;self.wrong_device=False;outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.calls.append(body);raw=json.dumps({'device_id':'different-device' if outer.wrong_device else body['device_id'],'opened':not outer.bad}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  try:self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  except OSError as error:raise HarnessUnavailable('Protected HTTP fixture unavailable: '+str(error)) from error
  threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port);return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close()
class App:
 def __init__(self,temp,bridge):
  temp.chmod(0o777);self.temp=temp;self.db=temp/'kiosk.sqlite';svg=temp/'art.svg';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="180"><rect x="30" y="20" width="180" height="140" rx="10" fill="#d5b76d"/><path d="M40 60H200M40 110H200" stroke="#263830" stroke-width="6"/></svg>')
  second=temp/'art-b.svg';second.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="180"><circle cx="120" cy="90" r="65" fill="#376da5"/></svg>')
  cfg=temp/'config.json';cfg.write_text(json.dumps({'tokens':{'synthetic-device':{'id':'device-a','role':'device'},'synthetic-editor':{'id':'editor-a','role':'editor'},'synthetic-admin':{'id':'admin-a','role':'admin'}},'assets':{'art':str(svg),'art-b':str(second)},'settings_url':bridge.url}))
  self.p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','KIOSK_CONFIG':str(cfg),'KIOSK_DATABASE':str(self.db),'PORT':'0'},user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Server unavailable')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1000:];self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
  status=dict(line.split(':',1) for line in Path('/proc/'+str(self.p.pid)+'/status').read_text().splitlines() if ':' in line);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0
  Path('/private/results').mkdir(parents=True,exist_ok=True)
  with open('/private/results/service-isolation.jsonl','a') as f:f.write(json.dumps({'pid':self.p.pid,'uid':1000,'cap_eff':0,'live_pid_verified':True,'environment_keys':['HOME','KIOSK_CONFIG','KIOSK_DATABASE','PATH','PORT','PYTHONDONTWRITEBYTECODE']})+'\n')
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def request(self,path,body=None,token='synthetic-editor'):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def ok(self,path,body=None,token='synthetic-editor'):
  status,data=self.request(path,body,token);assert status==200,(status,data);return json.loads(data)
 def seed(self):
  for ident,order in [('category-b',2),('category-a',1)]:self.ok('/edit',{'kind':'categories','record':{'id':ident,'order':order,'text':{'en':'Storage '+ident[-1],'es':'Almacenamiento '+ident[-1]}}})
  for ident,order in [('product-b',2),('product-a',1)]:self.ok('/edit',{'kind':'products','record':{'id':ident,'order':order,'category_id':'category-a','asset_id':'art-b' if ident=='product-b' else 'art','text':{'en':'Shelf with adjustable levels '+ident[-1],'es':'Estante con niveles ajustables y espacio para materiales de diferentes tamaños '+ident[-1]}}})
  self.ok('/publish',{'change_id':'first'})
 def count(self,table):
  assert table in ['events','publications']
  with sqlite3.connect(self.db) as db:return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
 def browser(self,mode):
  from browser_check import exercise
  def publish_next():
   self.ok('/edit',{'kind':'categories','record':{'id':'category-a','order':1,'text':{'en':'Later catalogue','es':'Catálogo posterior'}}});self.ok('/publish',{'change_id':'delayed-publication'})
   return self.ok('/snapshot',token='synthetic-device')
  return exercise(self.url,self.temp,publish_next,mode)
def ru001(a,b):
 assert a.request('/')[0]==200 and a.ok('/snapshot')['version']==0
 for path in ['/store.py','/config.json','/kiosk.sqlite']:assert a.request(path)[0]>=400
 assert a.request('/snapshot',token='invalid')[0]>=400
 action={'kind':'categories','record':{'id':'c','order':1,'text':{'en':'One','es':'Uno'}},'actor_id':'admin-a','role':'admin'}
 assert a.request('/edit',action,'synthetic-device')[0]>=400
 original=json.dumps(action,sort_keys=True);a.ok('/edit',action);assert json.dumps(action,sort_keys=True)==original
 a.ok('/publish',{'change_id':'one'});s=a.ok('/snapshot',token='synthetic-device');assert 'tokens' not in json.dumps(s) and 'synthetic-editor' not in json.dumps(s)
def ru002(a,b):
 a.seed();before=a.ok('/snapshot')
 for record in [{'id':'bad','order':True,'text':{'en':'One','es':'Uno'}},{'id':'bad','order':1,'text':{'en':'One','es':''}}]:assert a.request('/edit',{'kind':'categories','record':record})[0]>=400
 for changed in [{'asset_id':'missing'},{'category_id':'missing'}]:
  row={'id':'bad','order':1,'text':{'en':'One','es':'Uno'},'category_id':'category-a','asset_id':'art',**changed};assert a.request('/edit',{'kind':'products','record':row})[0]>=400
 a.ok('/publish',{'change_id':'second'});after=a.ok('/snapshot');assert before['categories']==after['categories'] and before['products']==after['products']
 r=a.browser('content');assert r['category_order']==['category-a','category-b'] and r['product_order']==['product-a','product-b'] and r['translated'] and r['images'],r
def ru003(a,b):
 a.seed();r=a.browser('navigation');assert r['logo_category'] and r['back_product'] and r['back_category'] and all(not x['overflow'] and not x['truncated'] for x in r['layouts']),r
def ru004(a,b):
 a.seed()
 with ThreadPoolExecutor(max_workers=5) as pool:rows=list(pool.map(lambda _:a.ok('/publish',{'change_id':'same'}),range(5)))
 assert all(r['version']==2 for r in rows) and a.count('publications')==2
 a.ok('/edit',{'kind':'categories','record':{'id':'c-new','order':5,'text':{'en':'New','es':'Nuevo'}}});assert len(a.ok('/snapshot')['categories'])==2 and a.ok('/publish',{'change_id':'same'})['version']==2
 with sqlite3.connect(a.db) as db:old=db.execute('SELECT payload FROM publications WHERE version=1').fetchone()[0]
 assert len(json.loads(old)['categories'])==2
 r=a.browser('sync');assert r['atomic'] and r['offline_cache'] and r['stale'] and r['no_token'],r
 old=a.ok('/snapshot');a.close();other=App(a.temp,b)
 try:assert all(other.ok('/snapshot')[k]==old[k] for k in ['version','categories','products','assets'])
 finally:other.close()
def ru005(a,b):
 # Independent published-content fixture isolates existing bridge/analytics from unfinished editing.
 snapshot={'version':1,'categories':[{'id':'category-a','order':1,'text':{'en':'One','es':'Uno'}}],'products':[{'id':'product-a','category_id':'category-a','asset_id':'art','order':1,'text':{'en':'Shelf','es':'Estante'}},{'id':'product-b','category_id':'category-a','asset_id':'art','order':2,'text':{'en':'Shelf two','es':'Estante dos'}}],'assets':{}}
 subprocess.run([sys.executable,'-I','-c',"import sqlite3,sys;db=sqlite3.connect(sys.argv[1]);db.execute('INSERT INTO publications VALUES(?,?,?)',(1,'analytics-fixture',sys.stdin.read()));db.commit()",str(a.db)],input=json.dumps(snapshot),text=True,user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp'},check=True)
 payload={'device_id':'device-a','actor_id':'admin-a','role':'admin'}
 assert a.request('/settings',payload,'synthetic-device')[0]>=400 and not b.calls
 reply=a.ok('/settings',payload,'synthetic-admin');assert reply['device_id']=='device-a' and reply['opened'] is True;assert len(b.calls)==1 and all(b.calls[0].get(k)==v for k,v in {'device_id':'device-a','operation':'open_network_settings'}.items())
 b.bad=True;assert a.request('/settings',payload,'synthetic-admin')[0]>=400
 b.bad=False;count=len(b.calls)
 assert a.request('/settings',{'device_id':'unknown-device'},'synthetic-admin')[0]>=400 and len(b.calls)==count
 b.wrong_device=True
 try:assert a.request('/settings',payload,'synthetic-admin')[0]>=400
 finally:b.wrong_device=False
 assert len(b.calls)==count+1
 assert a.ok('/settings',payload,'synthetic-admin')['device_id']=='device-a'
 event={'event_id':'event-one','target_type':'product','target_id':'product-a','device_id':'invented'};row=a.ok('/track',event,'synthetic-device');assert row['device_id']=='device-a';assert all(a.ok('/track',event,'synthetic-device')[k]==row[k] for k in ['event_id','target_type','target_id','device_id'])
 assert a.count('events')==1
 for changed in [{'target_id':'missing'},{'target_type':'unknown'},{'target_id':'product-b'}]:assert a.request('/track',{**event,**changed},'synthetic-device')[0]>=400
 assert a.request('/analytics',token='synthetic-device')[0]>=400 
 events=a.ok('/analytics');assert len(events)==1 and all(events[0][k]==row[k] for k in ['event_id','target_type','target_id','device_id'])
def main():
 if not Path('/public_tests/browser_launcher.py').is_file():return {'harness_ok':False,'results':[],'error':'Public browser helper unavailable'}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  a=None
  try:
   with tempfile.TemporaryDirectory(prefix='sweclar-kiosk-') as temp,Bridge() as b:
    try:a=App(Path(temp),b);test(a,b)
    finally:
     if a:a.close()
   row={'ru_id':f'RU-{i:03}','passed':True}
  except HarnessUnavailable as e:return {'harness_ok':False,'results':[],'infrastructure_errors':[str(e)]}
  except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2000:]}
  rows.append(row)
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
