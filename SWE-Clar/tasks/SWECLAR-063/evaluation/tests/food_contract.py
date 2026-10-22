from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,traceback,sqlite3,base64,io
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageDraw,PngImagePlugin
os.environ['MEAL_PRIVATE_SENTINEL']=__import__('secrets').token_hex(24)
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
class App:
 def __init__(self,root):
  self.root=root;root.chmod(0o777);self.db=root/'meals.sqlite';self.clock=root/'clock.txt';self.clock.write_text('2030-01-01T10:00:00Z');self.photo=root/'synthetic.png';im=Image.new('RGB',(120,90),'#f5ebd6');draw=ImageDraw.Draw(im);draw.ellipse((20,8,100,82),fill='#dda047');draw.ellipse((40,25,82,68),fill='#6c8c50');info=PngImagePlugin.PngInfo();info.add_text('Creator','synthetic-metadata-to-remove');im.save(self.photo,pnginfo=info)
  cfg=root/'config.json';cfg.write_text(json.dumps({'tokens':{'synthetic-a':'user-a','synthetic-b':'user-b','synthetic-c':'user-c'},'users':{'user-a':{'follows':['user-b']},'user-b':{'follows':[]},'user-c':{'follows':[]}},'venues':{'venue-a':{'name':'Example venue A','address':'Synthetic address A','latitude':0.001,'longitude':0.002},'venue-b':{'name':'Example venue B','address':'Synthetic address B','latitude':0.002,'longitude':0.003}},'clock_file':str(self.clock)}))
  self.p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','FOOD_CONFIG':str(cfg),'FOOD_DATABASE':str(self.db),'PORT':'0'},user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Food server unavailable')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1500:];self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
  fields=dict(x.split(':',1) for x in Path(f'/proc/{self.p.pid}/status').read_text().splitlines() if ':' in x);assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def request(self,path,body=None,user='a'):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer synthetic-'+user,'Content-Type':'application/json'})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def ok(self,path,body=None,user='a'):
  status,data=self.request(path,body,user);assert 200<=status<300,(status,data);return json.loads(data)
 def upload(self,user='a',data=None):return self.ok('/upload',{'data':base64.b64encode(data if data is not None else self.photo.read_bytes()).decode()},user)['image_id']
 def post(self,ident,user='a',image=None,**changes):return self.ok('/post',{'post_id':ident,'image_id':image or self.upload(user),'food':'Example meal '+ident,'caption':'An independent test meal.','venue_id':'venue-a','user_id':'forged-user','created':'1900-01-01T00:00:00Z',**changes},user)
 def seed(self):
  for user in ['a','b','c']:
   self.clock.write_text('2030-01-01T1'+str('abc'.index(user))+':00:00Z');self.post('post-'+user,user,venue_id='venue-b' if user=='b' else 'venue-a')
 def browser(self,kind):
  from browser_check import exercise
  return exercise(self,kind)
def ru001(a):
 assert a.request('/')[0]==200 and a.request('/feed',user='invalid')[0] in range(400,500)
 for path in ['/store.py','/config.json','/meals.sqlite']:assert a.request(path)[0] in range(400,500)
 image=a.upload('b');assert a.request('/image/'+image)[0] in range(400,500)
 body={'post_id':'bad','image_id':image,'food':'Example','caption':'Example','venue_id':'venue-a','user_id':'user-b'};assert a.request('/post',body)[0] in range(400,500) and a.ok('/feed')==[]
 a.post('post-a');before=a.ok('/feed');assert before[0]['owner']=='user-a' and __import__('datetime').datetime.fromisoformat(before[0]['created'].replace('Z','+00:00')).timestamp()==1893492000;a.close();other=App(a.root)
 try:assert [(x['id'],x['owner'],x['created'],x['image_url']) for x in other.ok('/feed')]==[(x['id'],x['owner'],x['created'],x['image_url']) for x in before]
 finally:other.close()
def ru002(a):
 ident=a.upload();status,data=a.request('/image/'+ident);assert status==200
 with Image.open(io.BytesIO(data)) as image:assert image.format=='PNG' and image.size==(120,90) and 'Creator' not in image.info
 assert b'synthetic-metadata-to-remove' not in data
 jpeg=io.BytesIO();Image.new('RGB',(41,32),'blue').save(jpeg,format='JPEG');other=a.upload(data=jpeg.getvalue());assert other!=ident
 for data in [b'not an image',b'']:
  assert a.request('/upload',{'data':base64.b64encode(data).decode()})[0] in range(400,500)
 row=a.post('post-a',image=ident);assert a.post('post-a',image=ident)['created']==row['created']
 for change in [{'food':''},{'caption':''},{'image_id':'missing'},{'venue_id':'missing'},{'venue_id':None,'venue':{'name':'N','address':'A','latitude':True,'longitude':1}},{'venue_id':None,'venue':{'name':'N','address':'A','latitude':91,'longitude':1}}]:
  body={'post_id':'bad','image_id':ident,'food':'Example','caption':'Example','venue_id':'venue-a',**change};assert 400<=a.request('/post',body)[0]<500
  assert [x['id'] for x in a.ok('/feed')]==['post-a']
 assert [x['id'] for x in a.ok('/feed')]==['post-a']
 manual={'name':'Example manual venue','address':'Synthetic address','latitude':-0.001,'longitude':-0.002};r=a.post('manual',image=ident,venue_id=None,venue=manual);assert all(r['venue'][k]==v for k,v in manual.items())
 assert a.request('/post',{'post_id':'post-a','image_id':ident,'food':'Conflict','caption':'Example','venue_id':'venue-a'})[0] in range(400,500)
def ru003(a):
 a.seed();assert [r['id'] for r in a.ok('/feed')]==['post-b','post-a'];c=a.ok('/feed',user='c')[0];assert a.request(c['image_url'])[0] in range(400,500)
 a.clock.write_text('2030-01-01T11:00:00Z');a.post('post-b0','b');assert [r['id'] for r in a.ok('/feed')]==['post-b','post-b0','post-a']
 with tempfile.TemporaryDirectory(prefix='sweclar-food-ui-') as temp:
  other=App(Path(temp))
  try:other.seed();other.browser('feed')
  finally:other.close()
def ru004(a):
 a.seed();body={'post_id':'post-b','saved':True}
 with ThreadPoolExecutor(max_workers=5) as pool:rows=list(pool.map(lambda _:a.ok('/save',body),range(5)))
 assert all(r['saved'] for r in rows);assert not a.ok('/feed',user='b')[0]['saved']
 a.ok('/save',{'post_id':'post-b','saved':False});a.ok('/save',{'post_id':'post-b','saved':False});assert not next(x for x in a.ok('/feed') if x['id']=='post-b')['saved']
 for ident in ['post-a','post-c','missing']:assert a.request('/save',{'post_id':ident,'saved':True})[0] in range(400,500)
 a.browser('save')
def ru005(a):
 a.seed();personal=a.ok('/pins?mode=personal');friends=a.ok('/pins?mode=friends');assert [r['post_id'] for r in personal]==['post-a'] and [r['post_id'] for r in friends]==['post-b'];assert friends[0]['latitude']==0.002 and friends[0]['longitude']==0.003
 assert a.request('/pins?mode=invalid')[0] in range(400,500);a.browser('map')
