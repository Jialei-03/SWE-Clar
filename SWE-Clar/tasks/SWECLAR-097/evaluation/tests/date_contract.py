from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import os,json,sys,tempfile,subprocess,select,urllib.request,urllib.error,http.cookiejar,hashlib,hmac,secrets,threading,concurrent.futures,traceback
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
def date_record(v):
 return {k:v.get(k) for k in ['id','user','mode','match_id','place','product_id']}
def business(v):return {'credits':v['credits'],'dates':[{k:r.get(k) for k in ['id','user','mode','match_id','place','product_id']} for r in v['dates']]}
def assert_conflicting_replays(session,provider,requests):
 before=business(session.ok('/me'));confirmations=sum(x[0]=='/payments/confirm' for x in provider.calls)
 for path,body in requests:
  assert session.request(path,body)[0]>=400
  assert business(session.ok('/me'))==before
  assert sum(x[0]=='/payments/confirm' for x in provider.calls)==confirmations
class Session:
 def __init__(self,url):self.url=url;self.cookies=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.cookies))
 def request(self,path,body=None):
  try:
   with self.opener.open(urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}),timeout=6) as r:return r.status,r.read(),dict(r.headers)
  except urllib.error.HTTPError as e:return e.code,e.read(),dict(e.headers)
 def ok(self,path,body=None):
  status,raw,_=self.request(path,body);assert status==200,(status,raw);return json.loads(raw)
 def login(self,name):return self.ok('/login',{'username':name,'password':'synthetic-pass'})
sys.path.insert(0,'/public_tests')
from development_provider import Provider
class App:
 def __init__(self,root):
  self.root=root;root.chmod(0o777);self.provider=Provider();self.config=root/'config.json';self.db=root/'dates.sqlite';users=[]
  for name,credits in [('one',1),('two',2),('zero',0),('browser',1)]:
   salt=secrets.token_bytes(16);users.append({'id':name,'username':name,'name':name.title()+' fixture','salt':salt.hex(),'password_hash':hashlib.scrypt(b'synthetic-pass',salt=salt,n=16384,r=8,p=1).hex(),'credits':credits,'latitude':.01,'longitude':.02})
  cfg={'users':users,'matches':[{'id':'match-'+name,'name':'Synthetic match','users':[name,'synthetic-partner']} for name in ['one','two','zero','browser']]+[{'id':'alternate-zero','name':'Another synthetic match','users':['zero','synthetic-partner']}],'products':[{'id':name,'quantity':quantity,'amount_minor':amount,'currency':'EUR'} for name,quantity,amount in [('one',1,1000),('three',3,2700),('five',5,4000)]],'provider_url':self.provider.url,'provider_token':self.provider.token,'receipt_key':self.provider.key.hex()};self.config.write_text(json.dumps(cfg));self.start();self.sessions={}
  for name in ['one','two','zero']:s=Session(self.url);s.login(name);self.sessions[name]=s
  self.report=None
 def start(self):
  self.p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','PORT':'0','DATE_CONFIG':str(self.config),'DATE_DATABASE':str(self.db)},user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.stop();raise AssertionError('server unavailable')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1000:];self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
 def stop(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def close(self):self.stop();self.provider.close()
 def browser(self):
  if self.report is None:
   from browser_check import exercise
   self.report=exercise(self)
  return self.report

def action(name,ident,**extra):return {'id':ident,'match_id':'match-'+name,'place_id':'coffee-a',**extra}
def ru001(a):
 assert Session(a.url).request('/me')[0]>=400
 for path in ['/config.json','/store.py','/dates.sqlite']:assert a.sessions['one'].request(path)[0]>=400
 for s in a.sessions.values():
  raw=s.request('/me')[1].decode();assert a.provider.token not in raw and a.provider.key.hex() not in raw and 'password_hash' not in raw
 r=a.browser();assert not r['errors'] and not r['remote'] and r['paths']>=3 and all(not x['overflow'] and x['height']>100 for x in r['layouts'])
def ru002(a):
 s=a.sessions['one'];assert {p['id'] for p in s.ok('/places?q=ClEaR')}=={'coffee-a','pub-a'};assert s.ok('/places?q=unknown')==[]
 before=s.ok('/me');count=len(a.provider.payments)
 for ident in ['missing','shop-a']:assert s.request('/purchase',action('one','invalid-place-'+ident,place_id=ident,product_id='one'))[0]>=400
 assert business(s.ok('/me'))==business(before) and len(a.provider.payments)==count
 r=a.browser();assert set(r['venues'])=={'Clear coffee','Clear pub'} and abs(r['marker']['lat']-.03)<1e-8 and abs(r['marker']['lng']-.04)<1e-8, r

def ru003(a):
 s=a.sessions['one'];body=action('one','credit-once');r=s.ok('/credit',body);assert s.ok('/me')['credits']==0 and len(s.ok('/me')['dates'])==1;assert date_record(s.ok('/credit',body))==date_record(r)
 assert s.request('/credit',action('one','credit-twice'))[0]>=400
 zero=a.sessions['zero'];assert zero.request('/credit',action('zero','zero-credit'))[0]>=400
 two=a.sessions['two']
 def spend(i):
  x=Session(a.url);x.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(two.cookies));return x.request('/credit',action('two','race-'+str(i)))[0]
 with concurrent.futures.ThreadPoolExecutor(3) as pool:statuses=list(pool.map(spend,range(3)))
 assert sum(s==200 for s in statuses)==2 and sum(s>=400 for s in statuses)==1 and two.ok('/me')['credits']==0 and len(two.ok('/me')['dates'])==2
 r=a.browser();assert r['creditInitially'] and r['creditBalance']=='Available credits: 0' and 'credit' in r['creditDate'] and r['noCredit']

def ru004(a):
 s=a.sessions['zero'];expected=0
 for sku,quantity,amount in [('one',1,1000),('three',3,2700),('five',5,4000)]:
  body=action('zero','purchase-'+sku,product_id=sku,amount_minor=1,paid=True,user='foreign');r=s.ok('/purchase',body);expected+=quantity-1;assert s.ok('/me')['credits']==expected;count=len([x for x in a.provider.calls if x[0]=='/payments/confirm']);assert date_record(s.ok('/purchase',body))==date_record(r);assert len([x for x in a.provider.calls if x[0]=='/payments/confirm'])==count;assert a.provider.payments[body['id']]['amount_minor']==amount
 before=s.ok('/me')
 for fault in ['signature','wrong_user','wrong_amount','wrong_id','wrong_product','wrong_currency','unpaid']:
  a.provider.fault=fault;assert s.request('/purchase',action('zero','fault-'+fault,product_id='three'))[0]>=400;assert business(s.ok('/me'))==business(before)
 a.provider.fault=None
 r=a.browser();assert r['purchaseDelta']==2 and r['purchaseDateDelta']==1

def ru005(a):
 s=a.sessions['zero'];before=s.ok('/me');count=len(a.provider.payments)
 for extra in [{'match_id':'match-one'},{'product_id':'invalid'}]:assert s.request('/purchase',action('zero','invalid-'+str(len(extra)),product_id='one')|extra)[0]>=400
 assert business(s.ok('/me'))==business(before) and len(a.provider.payments)==count
 a.provider.fault='unavailable';assert s.request('/purchase',action('zero','fault-unavailable',product_id='three'))[0]>=400 and business(s.ok('/me'))==business(before)
 a.provider.fault=None
 assert a.sessions['one'].request('/purchase',action('one','purchase-three',product_id='three'))[0]>=400
 a.provider.fault='lost_response';body=action('zero','retry-after-loss',product_id='three');assert s.request('/purchase',body)[0]>=400 and business(s.ok('/me'))==business(before);s.ok('/purchase',body);assert s.ok('/me')['credits']==before['credits']+2
 expected=s.ok('/me');a.stop();a.start()
 for x in a.sessions.values():x.url=a.url
 assert business(s.ok('/me'))==business(expected)
 # Successful same-actor IDs must reject materially different requests, including after restart.
 def conflicting_replays():
  before=business(s.ok('/me'))
  original=action('zero','retry-after-loss',product_id='three')
  assert_conflicting_replays(s,a.provider,[('/purchase',{**original,'place_id':'pub-a'}),('/purchase',{**original,'match_id':'alternate-zero'}),('/purchase',{**original,'product_id':'five'}),('/credit',original)])
  assert date_record(s.ok('/purchase',original))==date_record(next(r for r in before['dates'] if r['id']==original['id']))
 conflicting_replays()
 credit=action('zero','conflict-credit');saved=s.ok('/credit',credit)
 assert_conflicting_replays(s,a.provider,[('/credit',{**credit,'place_id':'pub-a'}),('/credit',{**credit,'match_id':'alternate-zero'}),('/purchase',{**credit,'product_id':'one'})])
 assert date_record(s.ok('/credit',credit))==date_record(saved)
 r=a.browser();assert abs(r['initial']['lat']-.01)<1e-4 and abs(r['initial']['lng']-.02)<1e-4 and abs(r['returnCenter']['lat']-.01)<1e-4 and abs(r['returnCenter']['lng']-.02)<1e-4 and r['retryDelta']==2 and r['retryDateDelta']==1 and sum(x['user']=='browser' for x in a.provider.payments.values())==2, r

def main():
 rows=[];a=None
 with tempfile.TemporaryDirectory(prefix='sweclar-date-') as temp:
  try:
   a=App(Path(temp))
   for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
    try:test(a);passed=True;detail=''
    except Exception as e:passed=False;detail=repr(e)+' '+traceback.format_exc()[-1000:]
    rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
  except Exception as e:return {'harness_ok':False,'infrastructure_errors':[str(e)],'results':rows}
  finally:
   if a:a.close()
 if Path('/private/evidence').is_dir() and a and a.report is not None:Path('/private/evidence/browser-observations.json').write_text(json.dumps(a.report))
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
