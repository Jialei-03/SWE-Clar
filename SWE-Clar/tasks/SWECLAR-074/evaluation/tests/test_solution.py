from browser_support import *
from playwright.sync_api import sync_playwright
from datetime import datetime
from contextlib import contextmanager

@contextmanager
def app():
 with tempfile.TemporaryDirectory() as directory:
  a=App(Path(directory))
  try:yield a
  finally:a.close()

HOOK="""(()=>{let saved;window.__realViewers=[];Object.defineProperty(window,'Cesium',{configurable:true,get:()=>saved,set:value=>{const Original=value.Viewer;const Wrapped=new Proxy(Original,{construct(Target,args){const v=Reflect.construct(Target,args);window.__realViewers.push(v);return v}});saved=new Proxy(value,{get(target,key){return key==='Viewer'?Wrapped:Reflect.get(target,key)}})}})})();"""
POINTS="""window.__renderedPoints=()=>{
 const v=window.__realViewers[0],points=[],time=v.clock.currentTime;
 const value=x=>x&&typeof x.getValue==='function'?x.getValue(time):x;
 const entities=collection=>{for(const e of collection.values){const graphic=e.point||e.billboard,p=value(e.position);if(graphic&&e.show!==false&&value(graphic.show)!==false&&p)points.push({position:p,id:e})}};
 entities(v.entities);for(let i=0;i<v.dataSources.length;i++)entities(v.dataSources.get(i).entities);
 const visit=c=>{if(c.show===false)return;for(let i=0;i<c.length;i++){const p=c.get(i);if(p.show===false)continue;if((Cesium.PointPrimitive&&p instanceof Cesium.PointPrimitive)||(Cesium.Billboard&&p instanceof Cesium.Billboard))points.push({position:p.position,primitive:p,id:p.id});else if(typeof p.get==='function'&&typeof p.length==='number')visit(p)}};
 visit(v.scene.primitives);return points;
};"""
HOOK+=POINTS
GEO="""()=>{const v=window.__realViewers[0],e=window.__renderedPoints()[0],p=e?.position,s=p?Cesium.SceneTransforms.worldToWindowCoordinates(v.scene,p):null,r=v.canvas.getBoundingClientRect(),c=p?Cesium.Cartographic.fromCartesian(p):null,hit=s?v.scene.pick(s):null;return {width:r.width,height:r.height,screen:s,latitude:c?Cesium.Math.toDegrees(c.latitude):null,longitude:c?Cesium.Math.toDegrees(c.longitude):null,map:document.querySelector('#map').getBoundingClientRect().width,left:document.querySelector('#main-panel').getBoundingClientRect().width,right:document.querySelector('#camera-panel').getBoundingClientRect().width,picked:!!hit&&((e.primitive&&hit.primitive===e.primitive)||(e.id!==undefined&&hit.id===e.id))}}"""
@contextmanager
def browser(a):
 with sync_playwright() as p:
  proof=a.root/'browser-proof.json'
  b=p.chromium.launch(executable_path='/public_tests/browser_launcher.py',headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'],env={'PATH':WHITE_PATH,'HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  try:
   evidence=json.loads(proof.read_text());assert evidence['uid']==1000 and evidence['cap_eff']==0
   status=Path('/proc/'+str(evidence['pid'])+'/status').read_text();assert 'Uid:\t1000\t1000\t1000\t1000' in status
   page=b.new_page(viewport={'width':1280,'height':900});remote=[];errors=[]
   def route(r):
    if r.request.url.startswith(a.url+'/') or r.request.url.startswith(('data:','blob:')):r.continue_()
    else:remote.append(r.request.url);r.abort()
   page.route('**/*',route);page.on('pageerror',lambda e:errors.append(str(e)));page.add_init_script(HOOK);page.goto(a.url)
   page.locator('#username').fill('example-user');page.locator('#password').fill('synthetic-pass');page.get_by_role('button',name='Sign in',exact=True).click();page.locator('#console').wait_for(state='visible',timeout=6000)
   page.wait_for_function('window.__realViewers.length && window.__realViewers[0].canvas.width>0');page.wait_for_timeout(300)
   yield page
   assert not remote,remote;assert not errors,errors
  finally:b.close()

def selected(page,lat,lon,center=False):
 for _ in range(40):
  page.wait_for_timeout(100);g=page.evaluate(GEO)
  if g['picked'] and g['latitude'] is not None and abs(g['latitude']-lat)<1e-7 and abs(g['longitude']-lon)<1e-7:break
 assert g['latitude'] is not None and abs(g['latitude']-lat)<1e-7 and abs(g['longitude']-lon)<1e-7,g
 assert g['picked'],'Actual rendered point cannot be picked'
 if center:assert abs(g['screen']['x']-g['width']/2)<3 and abs(g['screen']['y']-g['height']/2)<3,g
 return g

def search(page):
 page.locator('#main-toggle').click();page.locator('#query').fill('ALPHA');page.get_by_role('button',name='Search',exact=True).click();page.locator('[data-location="location-a"]').click()

def test_ru_001_offline_scene():
 with app() as a:
  assert a.one.request('/')[0]==200 and 400<=a.one.request('/tracks')[0]<500;a.login()
  for path in ['/config.json','/store.py','/sessions.sqlite','/cesium/%2e%2e/%2e%2e/config.json']:assert 400<=a.one.request(path)[0]<500
  for endpoint in ['/me','/tracks','/locations']:
   payload=a.one.request(endpoint)[1].decode();assert a.hash not in payload and 'password_hash' not in payload and 'salt' not in payload
  with browser(a) as page:
   colors=[]
   for _ in range(30):
    page.wait_for_timeout(200)
    pixels=page.evaluate("""()=>new Promise(resolve=>{const v=window.__realViewers[0];const off=v.scene.postRender.addEventListener(()=>{off();resolve(v.canvas.toDataURL('image/png'))});v.scene.requestRender()})""")
    with Image.open(io.BytesIO(base64.b64decode(pixels.split(',')[1]))) as im:colors=im.convert('RGB').getcolors(1000000) or []
    if len(colors)>10:break
   assert len(colors)>10,'Empty WebGL framebuffer'
  assert (a.root/'config.json').read_bytes()==a.before

def test_ru_002_authentication():
 with app() as a:
  for body in [{'username':'example-user','password':'wrong'},{'username':'missing','password':'synthetic-pass'}]:assert 400<=a.two.request('/login',body)[0]<500
  status,raw,headers=a.two.request('/login',{'username':'example-user','password':'synthetic-pass'});assert 200<=status<300 and 'httponly' in headers['Set-Cookie'].lower() and a.hash not in raw.decode()
  token=next(iter(a.two.cookies)).value;a.login();assert next(iter(a.one.cookies)).value!=token
  assert token.encode() not in a.db.read_bytes();assert a.two.ok('/me')['username']=='example-user'
  a.two.ok('/logout',{});assert 400<=a.two.request('/me')[0]<500
  with browser(a) as page:
   page.reload();page.locator('#console').wait_for(state='visible');page.locator('#logout').click();page.locator('#login-panel').wait_for(state='visible');assert 400<=page.request.get(a.url+'/me').status<500
  session=a.one;a.close();restart=App(a.root)
  try:session.url=restart.url;assert session.ok('/me')['username']=='example-user'
  finally:restart.close()

def test_ru_003_panel_geometry():
 with app() as a, browser(a) as page:
  search(page)
  for width in [960,1280,1440]:
   page.set_viewport_size({'width':width,'height':900});page.locator('#main-toggle').click();closed=selected(page,.01,.02,True)
   page.locator('#main-toggle').click();left=selected(page,.01,.02,True);assert left['left']>50 and abs(closed['width']-left['width']-left['left'])<3
   page.locator('#camera-toggle').click();both=selected(page,.01,.02,True);assert both['right']>50 and abs(left['width']-both['width']-both['right'])<3
   page.locator('#main-toggle').click();right=selected(page,.01,.02,True);assert abs(right['width']-both['width']-both['left'])<3
   page.locator('#camera-toggle').click();again=selected(page,.01,.02,True);assert abs(again['width']-closed['width'])<3
   for g in [closed,left,both,right,again]:assert g['width']>100 and abs(g['map']-g['width'])<3
   page.locator('#main-toggle').click()

def test_ru_004_local_search():
 with app() as a:
  a.login();rows=a.one.ok('/locations?q=ALPHA');assert len(rows)==1 and rows[0]['id']=='location-a' and rows[0]['latitude']==.01 and rows[0]['longitude']==.02;assert not a.one.ok('/locations?q=missing')
  with browser(a) as page:search(page);selected(page,.01,.02,True)

def test_ru_005_rewind():
 with app() as a:
  a.login()
  for at,expected in [('2030-01-01T10:00:15Z',(.03,.04)),('2030-01-01T10:00:20Z',(.05,.06)),('2030-01-01T11:00:00%2B01:00',(.01,.02))]:
   r=a.one.ok('/rewind?id=track-a&at='+at);assert (r['sample']['latitude'],r['sample']['longitude'])==expected and r['name']=='Synthetic track' and r['description']=='Generated sample path'
   expected_seconds={.01:0,.03:10,.05:20}[expected[0]];assert datetime.fromisoformat(r['sample']['time'].replace('Z','+00:00')).timestamp()==datetime.fromisoformat('2030-01-01T10:00:00+00:00').timestamp()+expected_seconds
  for ident,at in [('track-a','2030-01-01T09:00:00Z'),('missing','2030-01-01T10:00:15Z')]:
   status,payload,_=a.one.request('/rewind?id='+ident+'&at='+at);assert 400<=status<500 and json.loads(payload)['error']=='not_found'
  with browser(a) as page:
   page.locator('#camera-toggle').click();page.locator('#track').select_option('track-a');page.locator('#at').fill('2030-01-01T10:00:15');page.get_by_role('button',name='Rewind',exact=True).click();selected(page,.03,.04)
   metadata=page.locator('#metadata').inner_text();assert 'Synthetic track' in metadata and 'Generated sample path' in metadata
   page.locator('#at').fill('2030-01-01T09:00');page.get_by_role('button',name='Rewind',exact=True).click();page.wait_for_function('window.__renderedPoints().length===0')
  assert (a.root/'config.json').read_bytes()==a.before
