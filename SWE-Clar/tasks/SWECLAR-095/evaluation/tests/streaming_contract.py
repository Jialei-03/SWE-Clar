from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,os,sys,shutil,tempfile,subprocess,select,urllib.request,urllib.error,sqlite3,importlib.util,traceback
from browser_probe import probe
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).parent
class App:
 def __init__(self,path):
  self.path=path;path.chmod(0o777);self.work=path/'source';shutil.copytree(ROOT,self.work,ignore=shutil.ignore_patterns('.git','node_modules','dist','__pycache__'));spec=importlib.util.spec_from_file_location('fixture',TESTS/'payment_fixture.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);self.fixture=m.Fixture(path);self.db=path/'data.sqlite'
  self.work.chmod(0o777);self.counter=0;p=subprocess.run(self.command('build'),cwd=self.work,env=self.public_env(),capture_output=True,text=True,timeout=40);self.built=p.returncode==0;self.build_error=p.stderr[-1000:];self.start();self.tokens={};self.browser_result=None
 def public_env(self):return {k:os.environ[k] for k in ['PATH','UI_NODE_MODULES','ESBUILD_BINARY_PATH']}|{'HOME':'/tmp'}
 def command(self,mode):
  self.counter+=1;self.proof=self.path/('process-'+str(self.counter)+'.json');return [sys.executable,'-I','/public_tests/service_launcher.py',mode,str(self.work),str(self.fixture.file),str(self.db),str(self.path),str(self.proof)]
 def start(self):
  self.p=subprocess.Popen(self.command('service'),env=self.public_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],7)[0]:raise RuntimeError('service unavailable')
  port=self.p.stdout.readline().strip()
  if not port.isdigit():raise RuntimeError('startup failed: '+self.p.stderr.read()[-1000:])
  record=json.loads(self.proof.read_text());status=dict(line.split(':',1) for line in Path('/proc/'+str(self.p.pid)+'/status').read_text().splitlines() if ':' in line);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0;record['live_pid_verified']=True
  Path('/private/results').mkdir(parents=True,exist_ok=True)
  with open('/private/results/service-isolation.jsonl','a') as f:f.write(json.dumps(record)+'\n')
  self.url='http://127.0.0.1:'+port
 def stop(self):
  if getattr(self,'p',None) is not None and self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def close(self):
  self.stop();self.fixture.close()
  try:
   subprocess.run([sys.executable,'-I','-c',"import pathlib,shutil,sys;[(shutil.rmtree(p) if p.is_dir() else p.unlink()) for p in pathlib.Path(sys.argv[1]).iterdir()]",str(self.path)],user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},check=True)
  except subprocess.CalledProcessError as exc:
   print("evaluator cleanup warning (TemporaryDirectory finalizer remains responsible): "+str(exc),file=sys.stderr)
 def req(self,path,data=None,token='',headers=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+token,**(headers or {})})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=7) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def ok(self,path,data=None,token=''):
  status,raw=self.req(path,data,token);assert status==200,(path,status,raw);return json.loads(raw)
 def user(self,email):
  if email not in self.tokens:
   status,raw=self.req('/register',{'email':email,'password':'synthetic-passphrase'});assert status==200 or (status>=400 and raw),raw;self.tokens[email]=self.ok('/login',{'email':email,'password':'synthetic-passphrase'})['token']
  return self.tokens[email]
 def browser(self,mode):
  self.user('browser@example.test');self.fixture.receipt('browser-credit','browser@example.test');return probe(self.url,mode)

def ru001(a):
 assert a.built,a.build_error
 token=a.user('persist@example.test');before=a.ok('/me',token=token);a.stop();a.start();assert all(a.ok('/me',token=token)[k]==before[k] for k in ['id','email','balance'])
 # A failed feature probe is recorded by its feature gate; basic availability stays independent.
 assert a.req('/')[0]==200 and a.req('/catalog')[0]>=400

def ru002(a):
 result=a.ok('/register',{'email':' Existing@Example.Test ','password':'synthetic-passphrase'});assert result['email']=='existing@example.test';token=a.user('existing@example.test')
 with sqlite3.connect(a.db) as db:assert db.execute('SELECT payment_id FROM users WHERE id=?',(result['id'],)).fetchone()[0]=='pay-existing'
 assert a.fixture.hits[0]==('GET','/accounts');assert len(a.fixture.accounts)==1 # Existing provider account is reused
 with ThreadPoolExecutor(4) as pool:rows=list(pool.map(lambda _:a.req('/register',{'email':'new@example.test','password':'synthetic-passphrase'}),range(4)))
 assert any(s==200 for s,_ in rows) and all(s==200 or (s>=400 and raw) for s,raw in rows),rows
 with sqlite3.connect(a.db) as db:assert db.execute('SELECT COUNT(*) FROM users WHERE email="new@example.test"').fetchone()[0]==1
 assert set(a.fixture.accounts)=={'existing@example.test','new@example.test'}
 account=a.fixture.accounts['new@example.test'];assert account['email']=='new@example.test'
 assert len({v['id'] for v in a.fixture.accounts.values()})==2
 with sqlite3.connect(a.db) as db:assert db.execute('SELECT payment_id FROM users WHERE email=?',('new@example.test',)).fetchall()==[(account['id'],)]

def ru003(a):
 t=a.user('search@example.test');assert [x['id'] for x in a.ok('/catalog?q=OTHER',token=t)]==['second'];assert [x['id'] for x in a.ok('/catalog',token=t)]==['tone','second'];assert a.ok('/catalog?q=missing',token=t)==[]
 r=a.browser('catalog');assert r['search'] and r['layout'] and r['login'] and not r['errors'],r

def ru004(a):
 t=a.user('buyer@example.test');a.fixture.receipt('credit','buyer@example.test');a.ok('/credit',{'transaction_id':'credit'},t)
 with ThreadPoolExecutor(4) as pool:assert all(s==200 or (s>=400 and raw) for s,raw in pool.map(lambda _:a.req('/credit',{'transaction_id':'credit'},t),range(4)))
 assert a.ok('/me',token=t)['balance']==9
 with ThreadPoolExecutor(4) as pool:rows=list(pool.map(lambda _:a.req('/license',{'track':'tone','cost':0},t),range(4)))
 assert any(s==200 for s,_ in rows) and all(s==200 or (s>=400 and raw) for s,raw in rows)
 assert a.ok('/me',token=t)['balance']==6 and a.ok('/licenses',token=t)==['tone']
 status,raw=a.req('/media/tone',token=t);assert status==200 and raw==(a.path/'tone.wav').read_bytes();assert a.req('/media/tone',token=t,headers={'Range':'bytes=12-23'})==(206,raw[12:24])
 other=a.user('unlicensed@example.test')
 def isolated_media():
  for token in [other,'']:
   for headers in [None,{'Range':'bytes=12-23'}]:
    status,body=a.req('/media/tone',token=token,headers=headers);assert status>=400 and body!=raw and body!=raw[12:24]
  assert a.ok('/licenses',token=other)==[] and a.ok('/me',token=other)['balance']==0
 isolated_media()
 a.stop();a.start();assert a.ok('/me',token=t)['balance']==6 and a.ok('/licenses',token=t)==['tone']
 isolated_media();assert a.req('/media/tone',token=t)==(200,raw)
 r=a.browser('playback');assert all(r[k] for k in ['balance','loading','audio','pause','resume','noRewind']),r

def ru005(a):
 t=a.user('security@example.test');a.fixture.receipt('bad','security@example.test');a.fixture.receipts['bad']['signature']='0'*64;assert a.req('/credit',{'transaction_id':'bad'},t)[0]>=400
 for tx,extra in [('wrong-user',{'payment_id':'elsewhere'}),('wrong-tx',{'transaction_id':'elsewhere'}),('pending',{'status':'pending'}),('negative',{'tokens':-2})]:
  a.fixture.receipt(tx,'security@example.test',**extra);assert a.req('/credit',{'transaction_id':tx},t)[0]>=400
 assert a.ok('/me',token=t)['balance']==0 and a.req('/license',{'track':'tone'},t)[0]>=400 and a.req('/license',{'track':'unknown'},t)[0]>=400
 assert a.req('/media/tone',token=t)[0]>=400 and a.req('/media/tone')[0]>=400
 for path in ['/server.py','/config.json','/data.sqlite']:assert a.req(path,token=t)[0]>=400
 for path in ['/','/app.js','/me','/catalog']:
  raw=a.req(path,token=t)[1];assert a.fixture.api_key.encode() not in raw and a.fixture.key.hex().encode() not in raw
 assert a.ok('/me',token=t)['balance']==0 and a.ok('/licenses',token=t)==[]
 a.ok('/logout',{},t);assert a.req('/me',token=t)[0]>=400
 assert a.browser('logout')['logout']
def main():
 if not all(Path('/public_tests',n).is_file() for n in ['service_launcher.py','browser_launcher.py','browser_isolation.py']):return {'harness_ok':False,'infrastructure_errors':['Required public process helper unavailable'],'results':[]}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  with tempfile.TemporaryDirectory(prefix='sweclar-streaming-') as temp:
   a=None
   try:a=App.__new__(App);a.__init__(Path(temp));test(a);passed=True;detail=''
   except Exception as e:passed=False;detail=repr(e)+' '+traceback.format_exc()[-1000:]
   finally:
    if a and hasattr(a,'fixture'):a.close()
   rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'scope':'Actual web/service component only; no DRM/native/security certification','results':rows}
if __name__=='__main__':print(json.dumps(main()))
