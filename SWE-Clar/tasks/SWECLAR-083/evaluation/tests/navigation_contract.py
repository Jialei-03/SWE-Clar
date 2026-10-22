from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,traceback,importlib.util,threading,math,shutil
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from copy import deepcopy
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent;NODE=os.environ.get('NODE_BIN','node')
class HarnessUnavailable(RuntimeError):pass
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests')
try:from browser_isolation import launch
except ImportError:launch=None

def invoke(state,action,client):
 r=subprocess.run([sys.executable,'-I','/public_tests/invoke.py',str(ROOT)],input=json.dumps([state,action,client]),capture_output=True,text=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'},timeout=15)
 assert r.returncode==0,r.stderr
 data=json.loads(r.stdout);assert json.dumps(data['state'],sort_keys=True)==json.dumps(state,sort_keys=True) and json.dumps(data['action'],sort_keys=True)==json.dumps(action,sort_keys=True),'Inputs mutated'
 proof=data['proof'];assert proof['uid']==1000 and proof['cap_eff']==0
 assert not any('PRIVATE' in k for k in proof['environment_keys'])
 Path('/private/results').mkdir(parents=True,exist_ok=True)
 with open('/private/results/worker-isolation.jsonl','a') as out:out.write(json.dumps(proof)+'\n')
 return data['result']

def network():return {'nodes':{'s':{'lat':0,'lon':0},'a':{'lat':0,'lon':0.01},'b':{'lat':0.01,'lon':0.01},'c':{'lat':0.01,'lon':0},'d':{'lat':0,'lon':-0.011},'e':{'lat':0.009,'lon':-0.011},'f':{'lat':0.009,'lon':0},'g':{'lat':0,'lon':0.02},'h':{'lat':0.02,'lon':0.02},'i':{'lat':0.02,'lon':0}},'edges':[['s','a'],['a','b'],['b','c'],['c','s'],['s','d'],['d','e'],['e','f'],['f','s'],['s','g'],['g','h'],['h','i'],['i','s']]}
class Provider:
 def __enter__(self):
  self.calls=[];self.data=network();self.fail=False;outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    outer.calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));raw=json.dumps(outer.data).encode();self.send_response(503 if outer.fail else 200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  try:self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  except OSError as error:raise HarnessUnavailable('Protected HTTP fixture unavailable: '+str(error)) from error
  threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port)+'/network';self.client=self.url;return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close()
class App:
 def __init__(self,provider,state_path):
  state_path.parent.chmod(0o777);proof=state_path.parent/'service-proof.json'
  self.p=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',str(ROOT),provider.url,str(state_path),str(proof)],env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_PRIVATE_SERVICE_SENTINEL':'private-parent'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Server failed to start')
  line=self.p.stdout.readline();assert line,'No server startup';self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
  record=json.loads(proof.read_text());status=dict(x.split(':',1) for x in Path(f'/proc/{self.p.pid}/status').read_text().splitlines() if ':' in x);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0
  Path('/private/results').mkdir(parents=True,exist_ok=True)
  with open('/private/results/service-isolation.jsonl','a') as out:out.write(json.dumps(record)+'\n')
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def request(self,path,a=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(a).encode() if a is not None else None,headers={'Content-Type':'application/json'})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def action(self,a):
  status,data=self.request('/action',a);assert status==200,(status,data);return json.loads(data)

def browser_probe(app):
 with sync_playwright() as pw:
  browser=launch(pw.chromium,headless=True)
  try:
   page=browser.new_page(viewport={'width':900,'height':1000});page.set_default_timeout(5000)
   page.goto(app.url);page.locator('#routes button').first.wait_for()
   result={'routes':page.locator('#routes button').count(),'polylines':page.locator('#map polyline').count()}
   page.locator('#routes button').first.click();page.wait_for_function("document.querySelector('#map .selected')")
   result['points']=page.locator('#map .selected').get_attribute('points')
   # Compare normalized rendered coordinates with selected geometry, accepting affine viewport choices.
   selected=json.loads(app.request('/state')[1])['selected_route']['geometry'];drawn=[list(map(float,v.split(','))) for v in result['points'].split()]
   assert len(drawn)==len(selected)
   for axis,key,sign in [(0,'lon',1),(1,'lat',-1)]:
    actual=[v[axis] for v in drawn];expected=[p[key] for p in selected];span=max(expected)-min(expected)
    if span:
     assert max(actual)>min(actual)
     for x,y in zip(actual,expected):assert abs((x-min(actual))/(max(actual)-min(actual)) - ((y-min(expected))/span if sign==1 else (max(expected)-y)/span))<1e-6
   page.get_by_role('button',name='Start navigation').click();page.wait_for_function("document.querySelector('#status').textContent==='Navigation active'")
   dark=page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor');page.locator('#theme').select_option('light');page.wait_for_function("document.documentElement.dataset.theme==='light'")
   result['colors_differ']=dark!=page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')
   page.reload();page.wait_for_function("document.documentElement.dataset.theme==='light' && document.querySelector('#map .selected')")
   result['restored']=page.locator('#status').inner_text()=='Navigation active';result['layouts']=[]
   for width in [360,768,1024]:
    page.set_viewport_size({'width':width,'height':1000});result['layouts'].append(page.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth})'))
   return result
  finally:browser.close()

def generate():return {'type':'generate_alternatives','start_node':'s','requested_miles':2.75,'tolerance':0.05,'candidates':[{'route_id':'forged','distance_miles':2.75,'geometry':[]}]}
def fixture_state():
 n=network()['nodes'];routes={}
 for name,path in [('fixture-east',['s','a','b','c','s']),('fixture-west',['s','d','e','f','s'])]:
  g=[deepcopy(n[k]) for k in path];routes[name]={'route_id':name,'geometry':g,'distance_miles':sum(oracle_meters(a,b) for a,b in zip(g,g[1:]))/1609.344}
 return {'alternatives':routes,'points':[],'alerts':[],'theme':'dark'}
def selected(fn,p):
 s=fixture_state();rid=next(iter(s['alternatives']));return fn(s,{'type':'select_route','route_id':rid},p.client)
def oracle_meters(a,b):
 lat1,lat2=map(math.radians,[a['lat'],b['lat']]);half_lat=(lat2-lat1)/2;half_lon=math.radians(b['lon']-a['lon'])/2
 h=math.sin(half_lat)**2+math.cos(lat1)*math.cos(lat2)*math.sin(half_lon)**2
 return 6371008.8*2*math.atan2(math.sqrt(h),math.sqrt(max(0,1-h)))
def oracle_loops(data,start):
 adjacency={n:set() for n in data['nodes']}
 for a,b,*unused in data['edges']:adjacency[a].add(b)
 paths=[(start,)];found=[]
 while paths:
  path=paths.pop(0)
  for node in adjacency[path[-1]]:
   if node==start and len(path)>=3:found.append(path+(start,))
   elif node not in path and len(path)<10:paths.append(path+(node,))
 return {tuple((data['nodes'][n]['lat'],data['nodes'][n]['lon']) for n in path):sum(oracle_meters(data['nodes'][a],data['nodes'][b]) for a,b in zip(path,path[1:]))/1609.344 for path in found}

def saved(path):
 r=subprocess.run([sys.executable,'-I','-c','from pathlib import Path;import sys;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())',str(path)],user=1000,group=1000,extra_groups=[],capture_output=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'},timeout=5);assert r.returncode==0,r.stderr;return r.stdout

def ru001(fn,p,root):
 original={'points':[]};a=generate();before=deepcopy([original,a]);r=fn(original,a,p.client);assert [original,a]==before and 'error' not in r
 path=root/'state.json';app=App(p,path)
 try:
  s=app.action(generate());assert json.loads(saved(path))==s;before=saved(path);status,data=app.request('/action',{'type':'set_theme','theme':'invalid'});assert status==400 and before==saved(path)
  for url in ['/solution.py','/state.json','/../server.py','/.env']:assert app.request(url)[0]==404
 finally:app.close()
 app=App(p,path)
 try:assert json.loads(app.request('/state')[1])==s
 finally:app.close()

def ru002(fn,p,root):
 s=fn({},generate(),p.client);assert 'error' not in s,s;rows=s['result']['routes'];assert len(rows)==2 and p.calls==[{'start_node':'s'}]
 assert all(2.75-0.05<=r['distance_miles']<=2.75+0.05 and len(r['geometry'])==5 and r['geometry'][0]==r['geometry'][-1] for r in rows)
 assert rows==sorted(rows,key=lambda r:(abs(r['distance_miles']-2.75),r['route_id']))
 # Independent known perimeter bounds (roughly four 1.112 km sides), rather than trusting supplied distance labels.
 for r in rows:assert 2.763<r['distance_miles']<2.765
 again=fn({},generate(),p.client);assert [(r['route_id'],r['geometry'],r['distance_miles']) for r in again['result']['routes']]==[(r['route_id'],r['geometry'],r['distance_miles']) for r in rows]
 p.data['edges'].append(['s','a']);assert [r['route_id'] for r in fn({},generate(),p.client)['result']['routes']]==[r['route_id'] for r in rows]
 old=deepcopy(s);r=fn(s,{**generate(),'requested_miles':1,'tolerance':0.01},p.client);assert 'error' in r and r['alternatives']==old['alternatives']
 for value in [-1,0,float('nan'),True]:assert 'error' in fn(s,{**generate(),'requested_miles':value},p.client)
 p.data=network();p.data['edges'] += [['b','s',999999],['c','a',0],['a','s',1]]
 expected=oracle_loops(p.data,'s');broad={**generate(),'requested_miles':5,'tolerance':5};r=fn({},broad,p.client);assert 'error' not in r,r
 got={tuple((p['lat'],p['lon']) for p in row['geometry']):row['distance_miles'] for row in r['result']['routes']};assert got.keys()==expected.keys()
 for path,value in got.items():assert math.isclose(value,expected[path],rel_tol=1e-12,abs_tol=1e-10)
 stable={path:row['route_id'] for row in r['result']['routes'] for path in [tuple((p['lat'],p['lon']) for p in row['geometry'])]}
 p.data['edges'].reverse();again=fn({},broad,p.client)
 assert {tuple((p['lat'],p['lon']) for p in row['geometry']):row['route_id'] for row in again['result']['routes']}==stable
 first=r['result']['routes'][0];exact={**generate(),'requested_miles':first['distance_miles'],'tolerance':0};assert any(row['route_id']==first['route_id'] for row in fn({},exact,p.client)['result']['routes'])
 fresh=fn({'selected_route':first,'navigation':{'active':True}},broad,p.client);assert 'selected_route' not in fresh and 'navigation' not in fresh
 p.data=network()
 p.fail=True;r=fn(s,generate(),p.client);assert 'error' in r and r['alternatives']==s['alternatives'];p.fail=False
 for value in [-1,True,float('inf')]:assert 'error' in fn(s,{**generate(),'tolerance':value},p.client)
 p.data['nodes']['a']['lat']=float('inf');assert 'error' in fn(s,generate(),p.client)

def ru003(fn,p,root):
 s=selected(fn,p);assert s['selected_route'] in s['alternatives'].values();s=fn(s,{'type':'place_point','lat':0.001,'lon':0.002},p.client);assert s['points'][-1]=={'lat':0.001,'lon':0.002}
 for a in [{'type':'select_route','route_id':'missing'},{'type':'place_point','lat':True,'lon':0},{'type':'place_point','lat':0,'lon':181}]:assert 'error' in fn(s,a,p.client)
 (root/'state.json').write_text(json.dumps(fixture_state()));app=App(p,root/'state.json')
 try:
  r=browser_probe(app);assert r['routes']==r['polylines']==2 and len(set(r['points'].split()))==4 and all(not v['overflow'] for v in r['layouts']),r
 finally:app.close()

def ru004(fn,p,root):
 assert 'error' in fn({}, {'type':'start_navigation'},p.client);s=selected(fn,p);s=fn(s,{'type':'start_navigation'},p.client)
 segment_controls(fn,p,s)
 pos=s['selected_route']['geometry'][0];near={'type':'progress','event_id':'near','position':pos,'off_route_meters':999,'threshold_meters':30};r=fn(s,near,p.client);assert r['result']['off_route'] is False and r['result']['distance_meters']<0.01 and r['alerts']==[]
 far={'type':'progress','event_id':'far','position':{'lat':0.05,'lon':0.05},'off_route_meters':0,'threshold_meters':30};r=fn(s,far,p.client);assert r['result']['off_route'] and r['result']['distance_meters']>1000 and len(r['alerts'])==1 and all(r['alerts'][0].get(k)==v for k,v in {'event_id':'far','kind':'off_route','vibrate':True}.items())
 again=fn(r,far,p.client);assert again['alerts']==r['alerts']
 for position in [{'lat':float('nan'),'lon':0},{'lat':0,'lon':False}]:
  failed=fn(r,{**far,'position':position},p.client);assert 'error' in failed and failed['navigation']==r['navigation']
 for threshold in [-1,True,float('inf')]:assert 'error' in fn(s,{**far,'threshold_meters':threshold},p.client)
 # Zero-distance point at the exact zero threshold is not off-route.
 assert fn(s,{**near,'threshold_meters':0},p.client)['result']['off_route'] is False

def segment_controls(fn,p,s):
 # These are analytically known distances to the east square, independent of
 # the candidate's returned distance and of its route-generation algorithm.
 radius=6371008.8
 for index,(lat,lon,expected) in enumerate([
  (0,.005,0),(-.001,.005,radius*math.radians(.001)),
  (-.001,-.001,math.hypot(radius*math.radians(.001),radius*math.cos(math.radians(.001))*math.radians(.001)))
 ]):
  thresholds=[30] if expected==0 else [expected-1,expected+1]
  for threshold in thresholds:
   r=fn(s,{'type':'progress','event_id':f'segment-{index}-{threshold}','position':{'lat':lat,'lon':lon},'threshold_meters':threshold},p.client)
   assert 'error' not in r,r
   assert math.isclose(r['result']['distance_meters'],expected,rel_tol=1e-9,abs_tol=1e-6)
   assert r['result']['off_route'] is (expected>threshold)
 # Nonzero exact boundary: use a point directly south of a horizontal segment.
 distance=radius*math.radians(.001)
 r=fn(s,{'type':'progress','event_id':'equal','position':{'lat':-.001,'lon':.005},'threshold_meters':distance},p.client)
 assert r['result']['off_route'] is False and r['alerts']==s['alerts']


def ru005(fn,p,root):
 s=selected(fn,p);s=fn(s,{'type':'start_navigation'},p.client);r=fn(s,{'type':'set_theme','theme':'light'},p.client);assert r['selected_route']==s['selected_route'] and r['navigation']==s['navigation'] and r['theme']=='light'
 assert 'error' in fn(r,{'type':'set_theme','theme':'pink'},p.client)
 (root/'state.json').write_text(json.dumps(fixture_state()));app=App(p,root/'state.json')
 try:
  r=browser_probe(app);assert r['colors_differ'] and r['restored'],r
 finally:app.close()

def main():
 if not all(Path('/public_tests',n).is_file() for n in ['invoke.py','server_launcher.py','browser_launcher.py','browser_isolation.py']):return {'harness_ok':False,'error':'Public process helper unavailable','results':[]}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  try:
   fn=invoke
   with tempfile.TemporaryDirectory(prefix='sweclar-navigation-') as temp,Provider() as p:test(fn,p,Path(temp))
   row={'ru_id':f'RU-{i:03}','passed':True}
  except HarnessUnavailable as e:return {'harness_ok':False,'results':[],'infrastructure_errors':[str(e)]}
  except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2200:]}
  rows.append(row)
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
