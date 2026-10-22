from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,urllib.parse,http.cookiejar,threading,traceback,sqlite3,shutil
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from decimal import Decimal,ROUND_HALF_UP
from playwright.sync_api import sync_playwright
sys.path.insert(0,"/public_tests")
from browser_isolation import launch
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent;NODE=os.environ.get('NODE_BIN','node')
PRICING={'roof_type':{'flat':0.005,'pitched':2},'material':{'tile':0.005},'extras':{'cleanup':0.005}}
class HarnessUnavailable(RuntimeError):pass
def current_fields(row):
 def project(value,keys):return None if value is None else {k:value[k] for k in keys}
 detection=project(row['detection'],['detection_id','address','area_m2','center','bounds'])
 quote=project(row['quote'],['quote_id','detection_id','address','area_m2','roof_type','material','extras','items','total'])
 if detection:
  detection['center']=project(detection['center'],['latitude','longitude'])
  detection['bounds']={k:project(detection['bounds'][k],['latitude','longitude']) for k in ['sw','ne']}
 if quote:quote['items']=[project(x,['kind','name','amount']) for x in quote['items']]
 return {'detection':detection,'quote':quote}
class Provider:
 def __enter__(self):
  self.calls=[];self.area=1.0;self.fail=False;self.bad_bounds=False;self.multiple=False;outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_GET(self):
    parsed=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(parsed.query);outer.calls.append((parsed.path,params))
    if parsed.path=='/maps/api/geocode/json':
     address=params.get('address',[''])[0];result={'status':'ZERO_RESULTS','results':[]}
     if address=='Synthetic address A':result={'status':'OK','results':[{'geometry':{'location':{'lat':0.001,'lng':0.002}}}]}
     if outer.multiple and result.get('results'):result['results']*=2
     if address=='Ambiguous':result={'status':'OK','results':[{'partial_match':True,'geometry':{'location':{'lat':0.001,'lng':0.002}}}]}
    else:result={'center':{'latitude':0.001,'longitude':0.002},'boundingBox':{'sw':{'latitude':0.0009,'longitude':0.0019},'ne':{'latitude':0.0011,'longitude':0.0021}},'solarPotential':{'wholeRoofStats':{'areaMeters2':outer.area}},'postalCode':'provider-private-field','name':'buildings/provider-private-id'}
    if outer.bad_bounds and 'boundingBox' in result:result['boundingBox']['ne']['latitude']=-99
    raw=json.dumps(result).encode();self.send_response(503 if outer.fail else 200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  try:self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  except OSError as error:raise HarnessUnavailable('Protected HTTP fixture unavailable: '+str(error)) from error
  threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port);return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close()
class Session:
 def __init__(self,url):self.url=url;self.cookies=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.cookies));self.request('/')
 def request(self,path,body=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  try:
   with self.opener.open(req,timeout=5) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def ok(self,path,body=None):
  status,data=self.request(path,body);assert status==200,(status,data);return json.loads(data)
class App:
 def __init__(self,p,root):
  self.root=root;root.chmod(0o777);self.db=root/'roof.sqlite';cfg=root/'config.json';cfg.write_text(json.dumps({'geocoding_url':p.url+'/maps/api/geocode/json','solar_url':p.url+'/v1/buildingInsights:findClosest','api_key':'synthetic-provider-key','pricing':PRICING}))
  self.p=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',str(ROOT),str(cfg),str(self.db),str(root/'service-proof.json')],env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_PRIVATE_SERVICE_SENTINEL':'private-parent-only'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Roof server failed to start')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1500:];self.url='http://127.0.0.1:'+str(json.loads(line)['port']);proof=json.loads((root/'service-proof.json').read_text());status=dict(x.split(':',1) for x in Path(f'/proc/{self.p.pid}/status').read_text().splitlines() if ':' in x);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0 and proof['parent_sentinel_absent'];Path('/private/results').mkdir(parents=True,exist_ok=True);open('/private/results/service-isolation.jsonl','a').write(json.dumps(proof)+'\n');self.one=Session(self.url);self.two=Session(self.url)
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def count(self,table):
  assert table in ['detections','quotes','leads']
  # The service owns its SQLite/WAL files. The verifier has no DAC override
  # capability; inspect as their owner rather than requiring world readability.
  code="import sqlite3,sys;db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(db.execute('SELECT count(*) FROM '+sys.argv[2]).fetchone()[0])"
  r=subprocess.run([sys.executable,'-I','-c',code,str(self.db),table],user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,text=True,timeout=10)
  assert r.returncode==0,r.stderr
  return int(r.stdout.strip())
 def detected(self):return self.one.ok('/detect',{'address':'Synthetic address A'})
 def seed_detection(self,area=1):
  d={'detection_id':'fixture-'+str(self.count('detections')),'address':'Synthetic address A','area_m2':area,'center':{'latitude':.001,'longitude':.002},'bounds':{'sw':{'latitude':.0009,'longitude':.0019},'ne':{'latitude':.0011,'longitude':.0021}}}
  sid=next(c.value for c in self.one.cookies if c.name=='session')
  r=subprocess.run([sys.executable,'-c',"import os,sqlite3,sys;os.setgroups([]);os.setgid(1000);os.setuid(1000);db=sqlite3.connect(sys.argv[1]);db.execute('INSERT INTO detections VALUES (?,?,?)',sys.argv[2:]);db.commit()",str(self.db),d['detection_id'],sid,json.dumps(d)],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,text=True);assert r.returncode==0,r.stderr
  return d
 def quoted(self):
  d=self.seed_detection();return self.one.ok('/quote',{'detection_id':d['detection_id'],'roof_type':'flat','material':'tile','extras':['cleanup']})
 def browser(self):
  with sync_playwright() as pw:
   browser=launch(pw.chromium,headless=True)
   try:
    page=browser.new_page(viewport={'width':390,'height':844})
    page.add_init_script("Object.defineProperty(window,'L',{configurable:true,set(v){Object.defineProperty(window,'L',{value:v,writable:true,configurable:true});window.__maps=[];v.Map.addInitHook(function(){window.__maps.push(this)})}})")
    page.goto(self.url);page.locator('[name=roof_type] option').first.wait_for(state='attached');page.locator('#detect input').fill('Synthetic address A');page.locator('#detect button').click();page.locator('#detected').wait_for(state='visible')
    assert page.locator('#map path').count()>0
    boxes=page.evaluate("window.__maps.flatMap(m=>{const r=[];m.eachLayer(l=>{if(l.getBounds){const b=l.getBounds();r.push([b.getSouth(),b.getWest(),b.getNorth(),b.getEast()])}});return r})")
    assert any(all(abs(v-w)<1e-9 for v,w in zip(b,[.0009,.0019,.0011,.0021])) for b in boxes),boxes
    page.locator('#quote button').click();page.locator('#estimate').wait_for(state='visible');assert '0.02' in page.locator('#total').inner_text()
    page.reload();page.locator('#estimate').wait_for(state='visible')
    # Hold the actual request and release it after the address has changed.
    page.route('**/detect',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'detection_id':'late','address':'Synthetic address A','area_m2':1,'center':{'latitude':.001,'longitude':.002},'bounds':{'sw':{'latitude':.0009,'longitude':.0019},'ne':{'latitude':.0011,'longitude':.0021}}})))
    page.evaluate("document.querySelector('#detect').dispatchEvent(new Event('submit',{cancelable:true}));document.querySelector('#detect input').value='Different address';document.querySelector('#detect input').dispatchEvent(new Event('input'))")
    page.wait_for_timeout(250);assert page.locator('#detected').is_hidden() and page.locator('#estimate').is_hidden()
   finally:browser.close()

def ru001(a,p):
 detection=a.detected();q=a.quoted();assert a.count('quotes')==1
 sid=next(c.value for c in a.one.cookies if c.name=='session');action={'detection_id':q['detection_id'],'roof_type':'flat','material':'tile','extras':['cleanup']}
 r=subprocess.run([sys.executable,'-I','/public_tests/invoke_store.py',str(ROOT),str(a.root/'config.json'),str(a.db),sid,json.dumps(action)],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,text=True,timeout=5);assert r.returncode==0,r.stderr;result=json.loads(r.stdout);assert result['action']==action
 detection=a.one.ok('/current')['detection'];before=a.one.ok('/current');assert before['detection']==detection and current_fields(a.two.ok('/current'))=={'detection':None,'quote':None}
 for path in ['/provider.py','/store.py','/config.json','/roof.sqlite','/../store.py']:assert a.one.request(path)[0]==404
 assert 'synthetic-provider-key' not in json.dumps(before) and 'provider-private' not in json.dumps(before)
 cookies=a.one.cookies;a.close();new=App(p,a.root)
 try:
  session=Session(new.url);session.cookies=cookies;session.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(cookies));assert current_fields(session.ok('/current'))==current_fields(before)
 finally:new.close()

def ru002(a,p):
 d=a.detected();assert d['area_m2']==1 and d['center']=={'latitude':0.001,'longitude':0.002};assert len(p.calls)==2
 assert p.calls[0]==('/maps/api/geocode/json',{'address':['Synthetic address A'],'key':['synthetic-provider-key']})
 assert p.calls[1]==('/v1/buildingInsights:findClosest',{'location.latitude':['0.001'],'location.longitude':['0.002'],'key':['synthetic-provider-key']})
 before=a.one.ok('/current');count=a.count('detections')
 for address in ['Missing','Ambiguous','']:
  assert a.one.request('/detect',{'address':address,'roof_records':[{'area_m2':999}]})[0]!=200 and current_fields(a.one.ok('/current'))==current_fields(before) and a.count('detections')==count
 for value in [0,-1,float('nan'),True]:
  p.area=value;assert a.one.request('/detect',{'address':'Synthetic address A'})[0]!=200 and a.count('detections')==count
 p.area=1;p.bad_bounds=True;assert a.one.request('/detect',{'address':'Synthetic address A'})[0]!=200 and a.count('detections')==count
 p.bad_bounds=False;p.multiple=True;assert a.one.request('/detect',{'address':'Synthetic address A'})[0]!=200 and a.count('detections')==count
 p.multiple=False;p.fail=True;assert a.one.request('/detect',{'address':'Synthetic address A'})[0]!=200 and a.count('detections')==count

def ru003(a,p):
 d=a.seed_detection();r=a.one.ok('/quote',{'detection_id':d['detection_id'],'roof_type':'flat','material':'tile','extras':[],'area_m2':9999,'authorized':True,'override':{'authorized':True,'area_m2':9999}});assert r['area_m2']==1
 before=a.count('quotes');assert a.two.request('/quote',{'detection_id':d['detection_id'],'roof_type':'flat','material':'tile','extras':[]})[0]!=200 and a.count('quotes')==before
 a.browser()

def ru004(a,p):
 q=a.quoted();assert [i['amount'] for i in q['items']]==['0.01','0.01','0.01'] and q['total']=='0.03',q
 d=a.one.ok('/current')['detection'];payload={'detection_id':d['detection_id'],'roof_type':'flat','material':'tile','extras':['cleanup']};again=a.one.ok('/quote',payload);assert [(x['name'],x['amount']) for x in again['items']]==[(x['name'],x['amount']) for x in q['items']] and again['total']==q['total']
 before=a.count('quotes')
 for rate in [-1,True,'NaN','Infinity','invalid']:
  cfg=json.loads((a.root/'config.json').read_text());cfg['pricing']['material']['tile']=rate;(a.root/'invalid-config.json').write_text(json.dumps(cfg));sid=next(c.value for c in a.one.cookies if c.name=='session');r=subprocess.run([sys.executable,'-I','/public_tests/invoke_store.py',str(ROOT),str(a.root/'invalid-config.json'),str(a.db),sid,json.dumps(payload)],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,text=True,timeout=5);assert r.returncode!=0 and a.count('quotes')==before
 for changed in [{'roof_type':'missing'},{'material':'missing'},{'extras':['missing']},{'extras':['cleanup','cleanup']},{'detection_id':'missing'}]:assert a.one.request('/quote',{**payload,**changed})[0]!=200 and a.count('quotes')==before
 d=a.seed_detection(123.45);q=a.one.ok('/quote',{'detection_id':d['detection_id'],'roof_type':'pitched','material':'tile','extras':[]});assert {x['name']:x['amount'] for x in q['items']}=={'pitched':'246.90','tile':'0.62'} and q['total']=='247.52'

def ru005(a,p):
 q=a.quoted();body={'lead_id':'sample-lead','quote_id':q['quote_id'],'name':'Example Person','email':'example@example.test','phone':'+1 202 555 0100','address':q['address'],'quote':{'total':'0.00'}}
 first=a.one.ok('/lead',body);assert first['quote']==q and a.count('leads')==1
 with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(lambda _:a.one.ok('/lead',body),range(5)))
 assert all(all(r[k]==first[k] for k in [*body.keys()-{'quote'},'quote']) for r in results) and a.count('leads')==1
 assert a.two.request('/lead',body)[0]!=200 and a.two.request('/lead',{**body,'lead_id':'foreign-attempt'})[0]!=200 and a.count('leads')==1
 for changes in [{'name':''},{'email':''},{'phone':''},{'address':'Other address'},{'quote_id':'missing'}]:assert a.one.request('/lead',{**body,'lead_id':'bad',**changes})[0]!=200 and a.count('leads')==1

def main():
 missing=[name for name in ['server_launcher.py','browser_launcher.py','browser_isolation.py','invoke_store.py'] if not (Path('/public_tests')/name).is_file()]
 if missing:return {'harness_ok':False,'error':'Missing public harness helpers','infrastructure_errors':missing,'results':[]}
 results=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  a=None
  try:
   with tempfile.TemporaryDirectory(prefix='sweclar-roof-') as temp,Provider() as p:
    try:a=App(p,Path(temp));test(a,p)
    finally:
     if a:a.close()
   row={'ru_id':f'RU-{i:03}','passed':True}
  except HarnessUnavailable as e:return {'harness_ok':False,'results':[],'infrastructure_errors':[str(e)]}
  except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2200:]}
  results.append(row)
 return {'harness_ok':True,'results':results}
if __name__=='__main__':print(json.dumps(main()))
