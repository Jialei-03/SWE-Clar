from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,http.cookiejar,hashlib,sqlite3,traceback,base64,io
from PIL import Image
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
WHITE_PATH='/usr/local/bin:/usr/bin:/bin'
os.environ['CONSOLE_PRIVATE_SENTINEL']='private-evaluator-canary'
class Session:
 def __init__(self,url):self.url=url;self.cookies=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.cookies))
 def request(self,path,body=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  try:
   with self.opener.open(req,timeout=5) as r:return r.status,r.read(),dict(r.headers)
  except urllib.error.HTTPError as e:return e.code,e.read(),dict(e.headers)
 def ok(self,path,body=None):
  status,data,_=self.request(path,body);assert 200<=status<300,(status,data);return json.loads(data)
class App:
 def __init__(self,root):
  root.chmod(0o777);self.root=root;self.db=root/'sessions.sqlite';salt=b'independent-salt';self.hash=hashlib.scrypt(b'synthetic-pass',salt=salt,n=16384,r=8,p=1).hex();cfg=root/'config.json';self.config={'users':{'example-user':{'name':'Example User','salt':salt.hex(),'password_hash':self.hash}},'locations':[{'id':'location-a','name':'Alpha clearing','latitude':0.01,'longitude':0.02},{'id':'location-b','name':'Beta clearing','latitude':0.03,'longitude':0.04}],'tracks':[{'id':'track-a','name':'Synthetic track','description':'Generated sample path','samples':[{'time':'2030-01-01T10:00:20Z','latitude':0.05,'longitude':0.06},{'time':'2030-01-01T10:00:00Z','latitude':0.01,'longitude':0.02},{'time':'2030-01-01T10:00:10Z','latitude':0.03,'longitude':0.04}]}]};cfg.write_text(json.dumps(self.config));self.before=cfg.read_bytes()
  self.p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,user=1000,group=1000,extra_groups=[],env={'PATH':WHITE_PATH,'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','CONSOLE_CONFIG':str(cfg),'CONSOLE_DATABASE':str(self.db),'CESIUM_ASSET_DIR':'/opt/sweclar/cesium/Build/Cesium','PORT':'0'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],5)[0]:self.close();raise AssertionError('Console server unavailable')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1200:];self.url='http://127.0.0.1:'+str(json.loads(line)['port']);self.one=Session(self.url);self.two=Session(self.url);self.report=None
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def login(self):return self.one.ok('/login',{'username':'example-user','password':'synthetic-pass'})
