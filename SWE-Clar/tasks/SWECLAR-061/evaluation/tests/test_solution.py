import base64,hashlib,io,json,os,secrets,subprocess,sys,sqlite3
from PIL import Image
from pypdf import PdfReader
from transport import App,ROOT,WHITE_PATH

def image_bytes():
 image=Image.new('RGB',(60,40),(220,30,40));image.paste((30,40,220),(30,0,60,40));exif=Image.Exif();exif[274]=6;exif[270]='SYNTHETIC_METADATA_REMOVE';out=io.BytesIO();image.save(out,format='JPEG',quality=95,exif=exif);return out.getvalue()
def check_image(raw):
 image=Image.open(io.BytesIO(raw));image.load();assert image.format=='JPEG' and image.size==(40,60);assert not image.getexif() and b'SYNTHETIC_METADATA_REMOVE' not in raw
 for pos,expected in [((20,15),(220,30,40)),((20,45),(30,40,220))]:assert all(abs(a-b)<16 for a,b in zip(image.getpixel(pos),expected))
def report_fields(actual,expected):
 for key in ['id','room','title','details','complete']:assert actual[key]==expected[key]
 assert [(a['id'],a['kind']) for a in actual['assets']]==[(a['id'],a['kind']) for a in expected['assets']]

def payment_records(database,payment,user):
 # The supplied payments table is the persisted accounting boundary.
 with sqlite3.connect(database) as db:
  assert db.execute('SELECT id,user,plan FROM payments').fetchall()==[(payment,user,'basic')]

def test_ru_001_persistence_and_service_boundary():
 with App() as a:
  u=a.account('restart@example.test');ident=a.seed('persist',u);data=image_bytes()
  for kind in ['image','receipt']:a.upload(u,ident,kind,data,kind)
  before=a.ok('/report/'+ident,token=u['token']);a.stop();a.start();report_fields(a.ok('/report/'+ident,token=u['token']),before)
  for kind in ['image','receipt']:check_image(a.request('/assets/'+kind,token=u['token'])[1])
  a.deny('/content')
  for path in ['/config.json','/server.py','/data.sqlite']:a.deny(path,token=u['token'])
  assert b'synthetic-passphrase' not in a.db.read_bytes()

def test_ru_002_account_session_and_owner_regression():
 # Existing public password-derivation helper is validated against an independent scrypt oracle.
 salt=secrets.token_hex(16);r=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'password':'synthetic-passphrase','salt':salt}),capture_output=True,text=True,user=1000,group=1000,extra_groups=[],cwd=ROOT,env={'PATH':WHITE_PATH,'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},timeout=15)
 assert r.returncode==0;assert json.loads(r.stdout)['result']==hashlib.scrypt(b'synthetic-passphrase',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
 with App() as a:
  u=a.account(' Mixed@EXAMPLE.test ');token=u['token'];assert a.ok('/me',token=token)['email']=='mixed@example.test'
  a.deny('/register',{'email':'mixed@example.test','password':'synthetic-passphrase'});a.deny('/login',{'email':'mixed@example.test','password':'wrong-password'})
  assert a.ok('/login',{'email':' MIXED@example.test ','password':'synthetic-passphrase'})['id']==u['id']
  ident=a.seed('owned',u);other=a.account('other@example.test');a.ok('/trial',{},other['token'])
  for path,data in [('/report/'+ident,None),('/edit',{'id':ident,'title':'intruder','details':'changed'}),('/complete',{'id':ident}),('/content',{'id':'alien','room':'owned-room','title':'x','details':'x'})]:a.deny(path,data,other['token'])
  assert a.ok('/content',token=other['token'])==[] and a.ok('/rooms',token=other['token'])==[]
  a.ok('/logout',{},token);a.deny('/me',token=token)

def test_ru_003_trial_conflict_and_receipt_regression():
 with App() as a:
  u=a.account('trial@example.test');ident=a.seed('trial',u);token=u['token'];a.deny('/trial',{},token)
  assert a.ok('/report/'+ident,token=token)['title']=='Sample chair';a.ok('/edit',{'id':ident,'title':'Trial edited','details':'Visible during trial'},token)
  a.deny('/export/'+ident,token=token);a.deny('/share',{'id':ident},token)
  for name,extra in [('amount',{'amount':1}),('owner',{'user':'other'}),('currency',{'currency':'USD'}),('status',{'status':'pending'}),('identity',{'id':'mismatch'}),('plan',{'plan':'unknown'})]:
   a.receipt(u,name,**extra);a.deny('/activate',{'payment_id':name},token)
  a.receipt(u,'signature');a.receipts['signature']['signature']='0'*64;a.deny('/activate',{'payment_id':'signature'},token)
  paid=a.receipt(u,'payment/with space');first=a.ok('/activate',{'payment_id':paid},token);again=a.ok('/activate',{'payment_id':paid},token);assert first['plan']==again['plan']=='basic'
  payment_records(a.db,paid,u['id'])
  a.stop();a.start();assert a.ok('/me',token=token)['plan']=='basic';a.ok('/activate',{'payment_id':paid},token)
  payment_records(a.db,paid,u['id'])
  status,raw,_=a.request('/export/'+ident,token=token);assert 200<=status<300;text=''.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages);assert 'Trial edited' in text and 'Visible during trial' in text
  shared=a.ok('/share',{'id':ident},token);assert shared['title']=='Trial edited' and shared['details']=='Visible during trial'
  other=a.account('other-receipt@example.test');a.deny('/activate',{'payment_id':paid},other['token'])

def test_ru_004_actual_images_and_completed_edits():
 with App() as a:
  u=a.account('assets@example.test');ident=a.seed('assets',u);token=u['token'];data=image_bytes()
  a.deny('/content',{'id':'orphan','room':'missing','title':'x','details':'x'},token);a.deny('/content',{'id':'blank','room':'assets-room','title':'x','details':' '},token)
  for kind in ['image','receipt']:a.upload(u,ident,kind,data,kind)
  a.deny('/assets',{'id':'fake','content':ident,'kind':'image','data':base64.b64encode(b'not image').decode()},token)
  for kind in ['image','receipt']:check_image(a.request('/assets/'+kind,token=token)[1])
  other=a.account('other-assets@example.test');a.ok('/trial',{},other['token']);a.deny('/assets/image',token=other['token']);a.deny('/assets',{'id':'foreign','content':ident,'kind':'image','data':base64.b64encode(data).decode()},other['token'])
  a.ok('/complete',{'id':ident},token);a.ok('/edit',{'id':ident,'title':'Updated title','details':'After-completion revision'},token);a.upload(u,ident,'new-image',data)
  report=a.ok('/report/'+ident,token=token);assert report['complete']==1 and report['details']=='After-completion revision';assert {(x['id'],x['kind']) for x in report['assets']}=={('image','image'),('receipt','receipt'),('new-image','image')}

def test_ru_005_desktop_mobile_browser():
 from browser_check import exercise_browser
 with App() as a:exercise_browser(a,image_bytes())
