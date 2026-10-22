from pathlib import Path
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os,json,sys,tempfile,subprocess,select,urllib.request,urllib.error,http.cookiejar,sqlite3,secrets,hashlib,concurrent.futures,math,traceback
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests')
from browser_isolation import launch
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
def core(r):return {k:r[k] for k in ['id','user_id','site_id','latitude','longitude','started_at','ended_at','duration_seconds']}
def submit_response(page,selector,endpoint):
 with page.expect_response(lambda r:r.url.endswith(endpoint) and r.request.method=='POST') as pending:page.locator(selector).click()
 response=pending.value;response.finished();return response
def success_feedback(page,selector):
 page.wait_for_function('(selector)=>document.querySelector(selector).textContent.trim().length>0',arg=selector)
class Session:
 def __init__(self,url):self.url=url;self.cookies=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.cookies))
 def request(self,path,body=None):
  try:
   with self.opener.open(urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}),timeout=5) as r:return r.status,r.read(),dict(r.headers)
  except urllib.error.HTTPError as e:return e.code,e.read(),dict(e.headers)
 def ok(self,path,body=None):
  status,raw,_=self.request(path,body);assert status==200,(status,raw);return json.loads(raw)
 def account(self,email):self.ok('/register',{'email':email,'password':'synthetic-pass'});return self.ok('/login',{'email':email,'password':'synthetic-pass'})
class App:
 def __init__(self,root):
  self.root=root;root.chmod(0o777);self.db=root/'data.sqlite';self.clock=root/'clock';self.clock.write_text('1000');self.key=secrets.token_bytes(32).hex();config={'encryption_key':self.key,'sections':['Home','Sites','Plans','History','Account'],'sites':[{'id':'site-a','name':'Synthetic clearing','latitude':0,'longitude':0,'radius_m':100,'active':True},{'id':'site-b','name':'Inactive fixture','latitude':0,'longitude':0,'radius_m':100,'active':False}]};self.config=root/'config.json';self.config.write_text(json.dumps(config));self.start();self.one=Session(self.url);self.two=Session(self.url);self.report=None
 def start(self):
  self.p=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',str(ROOT),str(self.config),str(self.db),str(self.clock),str(self.root/'proof.json')],env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_PRIVATE_SENTINEL':'protected-parent'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('server unavailable')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1000:];self.url='http://127.0.0.1:'+str(json.loads(line)['port']);proof=json.loads((self.root/'proof.json').read_text());status=dict(x.split(':',1) for x in Path(f'/proc/{self.p.pid}/status').read_text().splitlines() if ':' in x);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0 and proof['parent_sentinel_absent'];Path('/private/results').mkdir(parents=True,exist_ok=True);open('/private/results/service-isolation.jsonl','a').write(json.dumps(proof)+'\n')
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def write_sql(self,sql,params):
  r=subprocess.run([sys.executable,'-c',"import os,sqlite3,sys,json;os.setgroups([]);os.setgid(1000);os.setuid(1000);db=sqlite3.connect(sys.argv[1]);db.execute(sys.argv[2],json.loads(sys.argv[3]));db.commit()",str(self.db),sql,json.dumps(params)],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},capture_output=True,text=True);assert r.returncode==0,r.stderr
 def browser(self,mode):
  with sync_playwright() as p:
   browser=launch(p.chromium,headless=True)
   try:
    context=browser.new_context(viewport={'width':820,'height':900},geolocation={'latitude':0,'longitude':0},permissions=['geolocation']);page=context.new_page();page.goto(self.url)
    page.locator('#email').fill('browser@example.test');page.locator('#password').fill('synthetic-pass');assert 200<=submit_response(page,'#register','/register').status<300;success_feedback(page,'#error');page.get_by_role('button',name='Sign in',exact=True).click();page.locator('#workspace').wait_for(state='visible')
    if mode=='navigation':
     assert page.locator('#nav button').all_text_contents()==['Home','Sites','Plans','History','Account']
     before=page.evaluate("fetch('/history').then(r=>r.json())")
     for width in [390,820]:
      page.set_viewport_size({'width':width,'height':900});buttons=page.locator('#nav button');plans=page.get_by_role('button',name='Plans',exact=True);center=page.evaluate("()=>{const p=document.querySelector('[data-section=Plans]').getBoundingClientRect(),n=document.querySelector('#nav').getBoundingClientRect();return Math.abs(p.x+p.width/2-n.x-n.width/2)}");assert center<2,{'width':width,'center_delta':center}
      # Prominence can use size, weight, or a distinct contrast treatment.
      styles=buttons.evaluate_all("bs=>bs.map(b=>{const s=getComputedStyle(b);return {height:b.getBoundingClientRect().height,font:parseFloat(s.fontSize),weight:parseInt(s.fontWeight)||400,bg:s.backgroundColor,color:s.color}})")
      primary=styles[2];others=styles[:2]+styles[3:];assert primary['height']>max(x['height'] for x in others) or primary['font']>max(x['font'] for x in others) or primary['weight']>max(x['weight'] for x in others) or all((primary['bg'],primary['color'])!=(x['bg'],x['color']) for x in others)
     for name in ['Plans','History','Account','Sites','Home']:
      page.get_by_role('button',name=name,exact=True).click();assert page.locator('#section').inner_text()==name
     assert page.evaluate("fetch('/history').then(r=>r.json())")==before
    elif mode=='gps':
     before=page.evaluate("fetch('/history').then(r=>r.json())")
     context.set_geolocation({'latitude':1,'longitude':1});assert 400<=submit_response(page,'#checkin','/checkin').status<500;success_feedback(page,'#status');assert page.evaluate("fetch('/history').then(r=>r.json())")==before
     context.set_geolocation({'latitude':0,'longitude':0});assert 200<=submit_response(page,'#checkin','/checkin').status<300;success_feedback(page,'#status')
     page.wait_for_function("async n=>{const rows=await fetch('/history').then(r=>r.json());return rows.length===n+1&&rows.some(r=>r.ended_at===null)}",arg=len(before))
     page.wait_for_function("document.querySelector('#history').textContent.trim().length>0")
     assert 200<=submit_response(page,'#checkout','/checkout').status<300;success_feedback(page,'#status')
     page.wait_for_function("async()=>{const rows=await fetch('/history').then(r=>r.json());return rows.length>0&&rows.every(r=>r.ended_at!==null)}");before=page.evaluate("fetch('/history').then(r=>r.json())")
     page.evaluate("()=>{navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail({code:1})}");page.locator('#checkin').click();page.wait_for_function("document.querySelector('#status').textContent==='location_unavailable'");assert page.evaluate("fetch('/history').then(r=>r.json())")==before
    page.reload();page.locator('#workspace').wait_for(state='visible');assert page.locator('#actor').inner_text()=='browser@example.test';page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');assert page.locator('#workspace').is_hidden()
   finally:browser.close()

def ru001(a):
 assert Session(a.url).request('/history')[0]!=200
 user=a.one.account(' One@EXAMPLE.test ');assert user['email']=='one@example.test'
 for path in ['/config.json','/store.py','/data.sqlite','/../config.json']:assert a.one.request(path)[0]==404
 for path in ['/me','/history','/sites','/navigation']:
  raw=a.one.request(path)[1].decode();assert a.key not in raw and all(x not in raw for x in ['password','verifier','salt','encryption_key'])
 raw=a.db.read_bytes();assert b'one@example.test' not in raw and b'synthetic-pass' not in raw and a.key.encode() not in raw
 with sqlite3.connect(a.db) as db:encrypted=db.execute('SELECT email FROM users WHERE id=?',(user['id'],)).fetchone()[0]
 blob=base64.b64decode(encrypted);assert json.loads(AESGCM(bytes.fromhex(a.key)).decrypt(blob[:12],blob[12:],b'checkin-fixture'))=='one@example.test'
 a.browser('account')

def ru002(a):
 a.one.account(' One@EXAMPLE.test ')
 assert a.one.request('/register',{'email':'ONE@example.test','password':'synthetic-pass'})[0]!=200
 assert a.two.request('/login',{'email':'one@example.test','password':'wrong-password'})[0]!=200
 status,raw,h=a.two.request('/login',{'email':' ONE@example.test ','password':'synthetic-pass'});assert status==200 and 'HttpOnly' in h['Set-Cookie'];token=next(iter(a.two.cookies)).value
 prior=token;a.two.ok('/login',{'email':'one@example.test','password':'synthetic-pass'});token=next(iter(a.two.cookies)).value;assert token!=prior
 with sqlite3.connect(a.db) as db:
  ident,salt,verifier=db.execute('SELECT id,salt,verifier FROM users WHERE id=?',(json.loads(raw)['id'],)).fetchone();assert bytes.fromhex(salt);assert db.execute('SELECT user FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]==ident
 probe=subprocess.run([sys.executable,'-I','/public_tests/account_probe.py',str(ROOT),str(a.config),str(a.db)],capture_output=True,text=True,timeout=10,env={'PATH':os.environ['PATH'],'HOME':'/tmp'});assert probe.returncode==0,probe.stderr;captured=json.loads(probe.stdout)
 with sqlite3.connect(a.db) as db:stored=db.execute('SELECT salt,verifier FROM users WHERE id=?',(captured['account']['id'],)).fetchone()
 assert any(call['salt']==stored[0] and call['result']==stored[1] for call in captured['scrypt_calls']),captured
 a.two.ok('/logout',{});assert a.two.request('/me')[0]!=200
 extra=Session(a.url);who=extra.account('disabled@example.test')
 with sqlite3.connect(a.db) as db:values=db.execute('SELECT salt,verifier FROM users').fetchall();assert len({v[0] for v in values})==len(values) and len({v[1] for v in values})==len(values)
 a.write_sql('UPDATE users SET active=0 WHERE id=?',[who['id']])
 assert extra.request('/me')[0]!=200 and extra.request('/login',{'email':'disabled@example.test','password':'synthetic-pass'})[0]!=200

def ru003(a):
 user=Session(a.url);user.account('gps@example.test');base={'id':'gps-1','site_id':'site-a','latitude':0,'longitude':0};before=user.ok('/history')
 for extra,status in [({'latitude':1,'distance_m':0},403),({'latitude':float('nan')},400),({'longitude':181},400),({'site_id':'site-b'},404)]:assert user.request('/checkin',{**base,**extra})[0]!=200
 assert user.ok('/history')==before
 inside=math.degrees(99.99/6371008.8);r=user.ok('/checkin',{**base,'latitude':inside,'distance_m':100000,'user_id':'someone-else','started_at':-1});assert r['started_at']==1000
 assert core(user.ok('/checkin',base))==core(r) and len(user.ok('/history'))==1
 assert user.request('/checkin',{**base,'site_id':'site-b'})[0]!=200 and len(user.ok('/history'))==1
 other=Session(a.url);other.account('other@example.test');assert other.request('/checkin',base)[0]!=200 and other.ok('/history')==[]
 user.ok('/checkout',{})
 boundary_latitude=math.degrees(100/6371008.8)
 boundary=user.ok('/checkin',{**base,'id':'boundary','latitude':boundary_latitude})
 assert boundary['id']=='boundary' and boundary['latitude']==boundary_latitude
 user.ok('/checkout',{})
 assert user.request('/checkin',{**base,'id':'outside','latitude':math.degrees(100.01/6371008.8)})[0]!=200
 a.browser('gps')

def ru004(a):
 actor=Session(a.url);actor.account('interval@example.test');body={'id':'interval-1','site_id':'site-a','latitude':0,'longitude':0};r=actor.ok('/checkin',body)
 assert actor.request('/checkin',{**body,'id':'interval-2'})[0]!=200
 a.clock.write_text('999');assert actor.request('/checkout',{})[0]!=200 and [core(x) for x in actor.ok('/history')]==[core(r)]
 a.clock.write_text('1042');closed=actor.ok('/checkout',{});assert closed['duration_seconds']==42 and closed['started_at']==1000;assert actor.request('/checkout',{})[0]!=200
 token=next(iter(actor.cookies)).value
 def attempt(i):
  s=Session(a.url);s.cookies=actor.cookies;s.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(s.cookies));return s.request('/checkin',{**body,'id':'race-'+str(i)})[0]
 with concurrent.futures.ThreadPoolExecutor(2) as pool:statuses=list(pool.map(attempt,range(2)))
 assert statuses.count(200)==1 and len(statuses)==2 and len(actor.ok('/history'))==2
 expected=actor.ok('/history');a.close();a.start();actor.url=a.url;a.one.url=a.url;a.two.url=a.url;assert actor.ok('/history')==expected
 with sqlite3.connect(a.db) as db:stored=' '.join(x[0] for x in db.execute('SELECT record FROM intervals'));assert 'site-a' not in stored and 'started_at' not in stored
 assert Session(a.url).request('/history')[0]!=200

def ru005(a):
 a.browser('navigation')

def main():
 try:import cryptography
 except ImportError:return {'harness_ok':False,'infrastructure_errors':['cryptography required'],'results':[]}
 missing=[name for name in ['server_launcher.py','browser_launcher.py','browser_isolation.py','account_probe.py'] if not (Path('/public_tests')/name).is_file()]
 if missing:return {'harness_ok':False,'infrastructure_errors':missing,'results':[]}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  a=None
  with tempfile.TemporaryDirectory(prefix='sweclar-checkin-') as temp:
   try:a=App(Path(temp));test(a);passed=True;detail=''
   except Exception as e:passed=False;detail=repr(e)+' '+traceback.format_exc()[-1600:]
   finally:
    if a:a.close()
  rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
