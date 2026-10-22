from pathlib import Path
import os,json,sys,secrets,re,subprocess,select,tempfile,urllib.request,urllib.error,traceback,threading,math,shutil,base64,io,csv,time,sqlite3,importlib.util
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from PIL import Image,PngImagePlugin
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
IDENTITIES={'review-fixture':{'id':'reviewer','role':'review'},'supplier-fixture':{'id':'first-user','role':'supplier','supplier_id':'first'},'other-fixture':{'id':'other-user','role':'supplier','supplier_id':'second'}}
os.environ['REGISTRATION_PRIVATE_SENTINEL']=secrets.token_hex(24)
def process_identity(pid):
 fields=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
 assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
class App:
 def __init__(self,root):
  self.root=root;(root/'data').mkdir(exist_ok=True);os.chmod(root/'data',0o777);self.db=root/'data/db.sqlite';identity=root/'identities.json';self.tokens={alias:secrets.token_hex(20) for alias in IDENTITIES};self.identities={self.tokens[k]:dict(v) for k,v in IDENTITIES.items()};self.identities[self.tokens['review-fixture']]['id']='review-'+secrets.token_hex(5);identity.write_text(json.dumps(self.identities));os.chmod(root,0o755);os.chmod(identity,0o644)
  self.p=subprocess.Popen([sys.executable,'/public_tests/server_launcher.py',str(ROOT/'server.py')],cwd=ROOT,env={'PATH':os.environ['PATH'],'HOME':'/tmp','PORT':'0','DATABASE_PATH':str(self.db),'IDENTITIES_PATH':str(identity),'PYTHONDONTWRITEBYTECODE':'1'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,user=1000,group=1000,extra_groups=[])
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Server failed to start')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1000:];self.url='http://127.0.0.1:'+str(json.loads(line)['port']);process_identity(self.p.pid)
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def request(self,path,a=None,token='review-fixture'):
  token=self.tokens.get(token,token)
  req=urllib.request.Request(self.url+path,data=json.dumps(a).encode() if a is not None else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=6) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def action(self,a,token='review-fixture'):
  status,data=self.request('/action',a,token);assert status==200,(status,data);return json.loads(data)
 def staff(self,token='review-fixture'):return json.loads(self.request('/staff',token=token)[1])
 def seed(self):
  for sid in ['first','second']:self.action({'type':'add_supplier','supplier_id':sid,'name':'Synthetic '+sid})
 def browser(self,review=False,export=False):
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
   downloads=self.root/'browser';downloads.mkdir(exist_ok=True);downloads.chmod(0o777);proof=downloads/'process.json'
   browser=p.chromium.launch(headless=True,executable_path='/public_tests/browser_launcher.py',downloads_path=str(downloads),env={'PATH':os.environ['PATH'],'HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
   attestation=json.loads(proof.read_text());process_identity(attestation['pid']);assert attestation['uid']==1000 and attestation['cap_eff']==0 and 'REGISTRATION_PRIVATE_SENTINEL' not in attestation['environment_keys']
   try:
    page=browser.new_page(viewport={'width':1024,'height':900},accept_downloads=True);page.set_default_timeout(5000)
    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.url) else route.abort())
    page.goto(self.url);page.get_by_label('Access token').fill(self.tokens['review-fixture']);page.get_by_role('button',name='Open workspace').click()
    name='Synthetic <img src=x onerror="window.__xss=1">'
    for label,value in [('Staff ID','browser-row'),('Supplier ID','first'),('Name',name),('Birth city','Example City')]:page.get_by_label(label,exact=True).fill(value)
    page.get_by_role('button',name='Submit registration').click();page.get_by_text(name,exact=True).wait_for()
    assert not page.evaluate('window.__xss || false')
    if review:
     with page.expect_response(lambda response:response.url.endswith('/action') and response.request.method=='POST') as response:
      page.get_by_role('button',name='Approve',exact=True).click()
     assert response.value.status==200
     page.get_by_text(re.compile(r'browser-row.*approved')).wait_for()
     assert any(row['staff_id']=='browser-row' and row['status']=='approved' for row in self.staff())
    if export:
     with page.expect_download() as info:page.get_by_role('button',name='Export CSV').click()
     data=Path(info.value.path()).read_text()
     assert any(row['staff_id']=='browser-row' for row in csv.DictReader(io.StringIO(data)))
    return {'reviewed':review,'safe_text':True,'exported':export}
   finally:browser.close()

def staff(ident='one',supplier='first'):return {'type':'register_staff','staff_id':ident,'supplier_id':supplier,'name':'Synthetic, "Person"','birth_city':'Example\nCity'}
def csv_bytes(rows):
 out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=['staff_id','supplier_id','name','birth_city','status','photo_id']);writer.writeheader();writer.writerows(rows);return out.getvalue()
def image(color='blue'):
 im=Image.new('RGB',(20,25),color);meta=PngImagePlugin.PngInfo();meta.add_text('Comment','synthetic metadata must be stripped');buff=io.BytesIO();im.save(buff,format='PNG',pnginfo=meta);return buff.getvalue()
def upload(a,ident='pic',supplier='first',color='blue'):
 a.action({'type':'upload_photo','asset_id':ident,'supplier_id':supplier,'media_type':'image/png','data':base64.b64encode(image(color)).decode()})

def ru001(a):
 a.seed();request=staff();before=deepcopy(request);a.action(request);assert request==before
 for token in ['', 'unknown']:
  for path in ['/staff','/history','/export.csv','/photo?id=pic']:assert a.request(path,token=token)[0] in (401,403)
 assert a.request('/action',staff('unauthorized'),token='')[0] in (401,403)
 for path in ['/store.py','/server.py','/identities.json','/db.sqlite','/../store.py']:assert a.request(path)[0] in (400,401,403,404)
 # The library must also preserve the action object.
 req=staff('direct');response=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'database':str(a.db),'identities':str(a.root/'identities.json'),'token':a.tokens['review-fixture'],'action':req}),text=True,capture_output=True,timeout=10,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'});result=json.loads(response.stdout);assert 'error' not in result and result['after']==req,result
 saved=a.staff();a.close();replacement=App(a.root)
 try:assert replacement.staff()==saved
 finally:replacement.close()

def ru002(a):
 a.seed()
 with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:a.request('/action',staff(),token='supplier-fixture')[0],range(6)))
 assert results.count(200)==1 and sum(400<=code<500 for code in results)==5,results
 a.action(staff('other','second'),'other-fixture');assert len(a.staff())==2 and [r['staff_id'] for r in a.staff('supplier-fixture')]==['one']
 for payload,token in [(staff('forged','second'),'supplier-fixture'),({**staff('bad'),'birth_city':''},'review-fixture'),(staff('orphan','missing'),'review-fixture')]:assert a.request('/action',payload,token)[0]!=200
 assert len(a.staff())==2
 payload={'type':'add_supplier','supplier_id':'bad','name':'invalid'};assert a.request('/action',payload,'supplier-fixture')[0] in (401,403)
 assert a.browser()['safe_text']


def ru003(a):
 a.seed();a.action(staff());before=a.staff();assert a.request('/action',{'type':'review','staff_id':'one','status':'approved','actor_id':'reviewer','role':'review','timestamp':1},'supplier-fixture')[0] in (401,403);assert a.staff()==before and json.loads(a.request('/history')[1])['audit']==[]
 lower=time.time_ns()//1000000;a.action({'type':'review','staff_id':'one','status':'approved','actor_id':'forged','timestamp':1});upper=time.time_ns()//1000000
 history=json.loads(a.request('/history')[1])['audit'];assert len(history)==1 and history[0]['actor_id']==a.identities[a.tokens['review-fixture']]['id'] and history[0]['old_status']=='submitted' and history[0]['new_status']=='approved' and (lower<=history[0]['timestamp']<=upper or lower//1000<=history[0]['timestamp']<=upper//1000)
 assert a.request('/action',{'type':'review','staff_id':'one','status':'rejected'})[0]!=200 and len(json.loads(a.request('/history')[1])['audit'])==1
 with sqlite3.connect(a.db) as db:
  stored=db.execute('SELECT status FROM staff WHERE id=?',('one',)).fetchone();audit=db.execute('SELECT actor_id,old_status,new_status FROM audit WHERE staff_id=?',('one',)).fetchall()
  assert stored==('approved',) and audit==[(a.identities[a.tokens['review-fixture']]['id'],'submitted','approved')]
 result=a.browser(review=True);assert result['reviewed'] and result['safe_text']


def ru004(a):
 a.seed();a.action(staff());upload(a);a.action({'type':'attach_photo','staff_id':'one','asset_id':'pic'})
 status,data=a.request('/photo?id=pic',token='supplier-fixture');assert status==200 and data.startswith(b'\x89PNG') and b'synthetic metadata' not in data
 with Image.open(io.BytesIO(data)) as im:assert im.size==(20,25) and im.convert('RGB').getpixel((5,5))==(0,0,255) and 'Comment' not in im.info
 assert a.request('/photo?id=pic',token='other-fixture')[0] in (401,403)
 upload(a,'next',color='green');a.action({'type':'attach_photo','staff_id':'one','asset_id':'next'});a.action({'type':'attach_photo','staff_id':'one','asset_id':'next'});hist=json.loads(a.request('/history')[1]);assert [r['photo_id'] for r in hist['photo_history']]==['pic']
 upload(a,'foreign','second');before=a.staff();assert a.request('/action',{'type':'attach_photo','staff_id':'one','asset_id':'foreign'})[0] in (401,403);assert a.staff()==before
 for raw,mime in [(b'not a photo','image/png'),(image(),'image/jpeg')]:assert a.request('/action',{'type':'upload_photo','asset_id':'bad','supplier_id':'first','media_type':mime,'data':base64.b64encode(raw).decode()})[0]!=200
 assert a.request('/action',{'type':'attach_photo','staff_id':'one','asset_id':'missing'})[0]!=200 and a.staff()==before


 # JPEG is decoded and stored as independently readable PNG; no format-name-only substitute.
 jpeg=io.BytesIO();Image.new('RGB',(17,19),(200,30,10)).save(jpeg,format='JPEG')
 a.action({'type':'upload_photo','asset_id':'jpeg','supplier_id':'first','media_type':'image/jpeg','data':base64.b64encode(jpeg.getvalue()).decode()},'supplier-fixture')
 with Image.open(io.BytesIO(a.request('/photo?id=jpeg',token='supplier-fixture')[1])) as photo:
  assert photo.format=='PNG' and photo.size==(17,19)
  actual=photo.convert('RGB').getpixel((3,3));assert all(abs(x-y)<=4 for x,y in zip(actual,(200,30,10)))
 oversize=io.BytesIO();Image.new('RGB',(2001,2000)).save(oversize,format='PNG')
 for ident,raw in [('large_pixels',oversize.getvalue()),('large_bytes',image()+bytes(2000001-len(image()))),('truncated',image()[:30])]:
  assert a.request('/action',{'type':'upload_photo','asset_id':ident,'supplier_id':'first','media_type':'image/png','data':base64.b64encode(raw).decode()})[0]!=200
 with sqlite3.connect(a.db) as db:
  assert db.execute('SELECT photo_id FROM staff WHERE id=?',('one',)).fetchone()==('next',)
  assert db.execute('SELECT photo_id FROM photo_history ORDER BY seq').fetchall()==[('pic',)]
  assert not db.execute("SELECT id FROM photos WHERE id IN ('large_pixels','large_bytes','truncated')").fetchall()


def ru005(a):
 a.seed();a.action(staff('z'));a.action(staff('a'));status,data=a.request('/export.csv');assert status==200;rows=list(csv.DictReader(io.StringIO(data.decode(),newline='')));assert [r['staff_id'] for r in rows]==['a','z'];assert rows[0]['name']==staff()['name'] and rows[0]['birth_city']==staff()['birth_city']
 for path in ['/export.csv','/history']:assert a.request(path,token='supplier-fixture')[0] in (401,403)
 cloned=[{**r,'staff_id':'copy-'+r['staff_id']} for r in rows];a.action({'type':'import','csv':csv_bytes(cloned)});saved=a.staff();assert len(saved)==4
 bad_batches=[[{**rows[0],'staff_id':'new'},rows[1]],[{**rows[0],'staff_id':'new','supplier_id':'missing'}],[{**rows[0],'staff_id':'new','status':'invalid'}],[{**rows[0],'staff_id':'new','photo_id':'missing'}]]
 for batch in bad_batches:
  assert a.request('/action',{'type':'import','csv':csv_bytes(batch)})[0]!=200 and a.staff()==saved
 assert a.request('/action',{'type':'import','csv':csv_bytes([])},'supplier-fixture')[0] in (401,403)
 assert a.request('/action',{'type':'import','csv':'staff_id,name\nx,y\n'})[0]!=200 and a.staff()==saved


 upload(a,'owned','first')
 for batch in [[{**rows[0],'staff_id':'fresh','supplier_id':'second','photo_id':'owned'}],[{**rows[0],'staff_id':'same'},{**rows[0],'staff_id':'same'}]]:
  assert a.request('/action',{'type':'import','csv':csv_bytes(batch)})[0]!=200 and a.staff()==saved
 # Column order is not a business rule; exactly the same columns in another order remain valid.
 out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=list(reversed(list(rows[0]))));writer.writeheader();writer.writerow({**rows[0],'staff_id':'reordered'})
 a.action({'type':'import','csv':out.getvalue()})
 with sqlite3.connect(a.db) as db:
  assert db.execute('SELECT COUNT(*) FROM staff').fetchone()==(5,)
  assert db.execute('SELECT name,birth_city FROM staff WHERE id=?',('reordered',)).fetchone()==(staff()['name'],staff()['birth_city'])
 assert a.browser(export=True)['exported']


def main():
 if not all(Path('/public_tests',name).is_file() for name in ['invoke.py','browser_launcher.py','server_launcher.py']):return {'harness_ok':False,'error':'Invocation helper unavailable','results':[]}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  a=None
  try:
   with tempfile.TemporaryDirectory(prefix='sweclar-registration-') as temp:
    try:a=App(Path(temp));test(a)
    finally:
     if a:a.close()
   row={'ru_id':f'RU-{i:03}','passed':True}
  except subprocess.TimeoutExpired:return {'harness_ok':False,'error':'Unattributed timeout','results':[]}
  except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2200:]}
  rows.append(row)
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
