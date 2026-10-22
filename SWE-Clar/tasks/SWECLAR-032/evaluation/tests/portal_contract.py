from pathlib import Path
import os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,traceback,shutil,socket,time
from copy import deepcopy
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent;NODE=os.environ.get('NODE_BIN','node')
def bootstrap():return {'centres':{'first':{'name':'Example first'},'second':{'name':'Example second'}},'children':{'child-a':{'centre_id':'first'},'child-b':{'centre_id':'first'},'child-c':{'centre_id':'second'}},'users':{key:{'role':role,'centre_ids':centres,'child_ids':children,'pin':'1357'} for key,role,centres,children in [('admin','admin',['first','second'],[]),('staff-first','staff',['first'],[]),('staff-second','staff',['second'],[]),('parent-first','parent',['first'],['child-a']),('parent-second','parent',['second'],['child-c'])]}}
def rows():return [{'legacy_id':ident,'record_type':kind,'centre_id':centre,'relationship_ids':[child],'child_id':child,'data':{'note':'Synthetic '+ident}} for ident,kind,centre,child in [('legacy-a','daily_chart','first','child-a'),('legacy-b','daily_chart','first','child-b'),('legacy-c','daily_chart','second','child-c'),('curriculum-a','curriculum','first','child-a'),('curriculum-b','curriculum','first','child-b'),('incident-a','incident','first','child-a')]]
PUBLIC=Path('/public_tests') if Path('/public_tests').is_dir() else TESTS.parent/'public_tests'
sys.path.insert(0,str(PUBLIC))
from database_fixture import MongoFixture
class InfrastructureError(RuntimeError):pass
class Mongo(MongoFixture):
 def __init__(self,root):
  super().__init__(root/'management');self.accounts={}
 def candidate_uri(self,name):
  if name not in self.accounts:self.accounts[name]=self.provision(name)
  return self.accounts[name]
class App:
 def __init__(self,mongo,root,dbname):
  self.root=root;self.mongo=mongo;self.dbname=dbname;project=root/'project';home=root/'home';root.chmod(0o755)
  if not project.exists():
   project.mkdir();home.mkdir()
   for path in [project,home]:os.chown(path,1000,1000)
   subprocess.run([sys.executable,'-I','-c',"import shutil,sys;shutil.copytree(sys.argv[1],sys.argv[2],dirs_exist_ok=True,ignore=shutil.ignore_patterns('runtime'))",str(ROOT),str(project)],user=1000,group=1000,extra_groups=[],check=True)
  config=root/'bootstrap.json'
  if not config.exists():config.write_text(json.dumps(bootstrap()));config.chmod(0o600);os.chown(config,1000,1000)
  env={k:os.environ[k] for k in ['PATH','NODE_PATH'] if k in os.environ}
  env.update(HOME=str(home),MONGODB_URI=mongo.candidate_uri(dbname),PORTAL_DATABASE=dbname,PORTAL_BOOTSTRAP=str(config))
  self.p=subprocess.Popen([NODE,str(project/'server.cjs')],cwd=project,env=env,user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],10)[0]:self.close();raise AssertionError('Portal did not start')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1800:];self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=8)
 def request(self,path,body=None,token=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=6) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def ok(self,path,body=None,token=None):
  status,data=self.request(path,body,token);assert status==200,(status,data);return json.loads(data)
 def login(self,user='admin',centre='first'):return self.ok('/login',{'user_id':user,'centre_id':centre,'pin':'1357'})['token']
 def seed(self):
  token=self.login();data=[{'_id':r['legacy_id'],**{k:v for k,v in r.items() if k!='legacy_id'}} for r in rows()];self.inspect("await db.collection('records').insertMany("+json.dumps(data)+");console.log('true');");return token
 def inspect(self,script):
  prefix="const {MongoClient}=require('mongodb');(async()=>{let input='';for await(const chunk of process.stdin)input+=chunk;const config=JSON.parse(input);const c=new MongoClient(config.uri);await c.connect();try{const db=c.db(config.database);"
  result=subprocess.run([NODE,'-e',prefix+script+"}finally{await c.close();}})().catch(e=>{console.error(e.message);process.exit(1)});",],input=json.dumps({'uri':self.mongo.admin_uri,'database':self.dbname}),env=os.environ,capture_output=True,text=True,timeout=10);assert result.returncode==0,result.stderr;return json.loads(result.stdout)

def ru001(a):
 token=a.seed();saved=a.ok('/api/records?module=daily_chart',token=token);assert len(saved)==3
 original=[{**rows()[0],'legacy_id':'immutability-probe','data':{'note':'Synthetic immutable input','nested':{'values':[1,2]}}}]
 for original in [original,[{**original[0],'child_id':'missing-child'}]]:
  payload={'uri':a.mongo.candidate_uri(a.dbname),'database':a.dbname,'project':str(a.root/'project'),'token':token,'rows':original}
  observed=subprocess.run([NODE,'-e',(TESTS/'input_probe.cjs').read_text()],input=json.dumps(payload),text=True,capture_output=True,timeout=15,user=1000,group=1000,extra_groups=[],cwd=a.root/'project',env={k:os.environ[k] for k in ['PATH','NODE_PATH'] if k in os.environ})
  assert observed.returncode==0,observed.stderr
  assert json.loads(observed.stdout)['rows']==original,'Migration mutated its caller-owned input'
 # This regression observes mutation even when the starter's missing migration throws.
 # Restore only the probe row; migration success and persistence are checked in RU002.
 a.inspect("await db.collection('records').deleteOne({_id:'immutability-probe'});console.log('true');")

 for path in ['/portal.cjs','/server.cjs','/bootstrap.json','/../portal.cjs']:assert a.request(path)[0]==404
 for path in ['/api/records?module=daily_chart','/api/messages']:assert a.request(path)[0]==403
 a.close();other=App(a.mongo,a.root,a.dbname)
 try:assert other.ok('/api/records?module=daily_chart',token=token)==saved
 finally:other.close()

def ru002(a):
 token=a.login();source=rows();source[0]['relationship_ids'].append('curriculum-a');source[3]['relationship_ids'].append('legacy-a');r=a.ok('/api/migrate',{'rows':source},token)
 # The delivery agreement specifies migration behavior but intentionally does
 # not reserve a response spelling for the inserted count.  Both names are
 # accepted; the numeric semantics and skipped count remain required.
 inserted=r.get('inserted',r.get('migrated'));assert inserted==6 and r.get('skipped')==0
 replay=a.ok('/api/migrate',{'rows':source},token);replay_inserted=replay.get('inserted',replay.get('migrated'));assert replay_inserted==0 and replay.get('skipped')==6
 stored=a.ok('/api/records?module=curriculum',token=token);row=next(x for x in stored if x['id']=='curriculum-a');assert row['relationship_ids']==['child-a','legacy-a'] and row['record_type']=='curriculum' and row['centre_id']=='first' and row['data']==source[3]['data']
 snapshot=lambda:a.inspect("console.log(JSON.stringify(await db.collection('records').find({}).sort({_id:1}).toArray()));")
 before_records=snapshot()
 # The first row can be inserted before discovering a conflicting replay; the transaction must roll it back.
 fresh={**rows()[0],'legacy_id':'new-record'};conflict={**source[1],'data':{'note':'conflicting replay'}}
 for batch in [[fresh,conflict],[fresh,{**fresh,'legacy_id':'bad','relationship_ids':['child-c']}],[fresh,{**fresh,'legacy_id':'bad','relationship_ids':['missing']}],[fresh,{**fresh,'legacy_id':'bad','child_id':'missing'}],[fresh,{**fresh,'legacy_id':'bad','child_id':'child-c'}],[fresh,{**fresh,'legacy_id':'bad','record_type':'unknown'}],[fresh,{**fresh,'legacy_id':'bad','data':None}],[fresh,fresh],None]:
  assert a.request('/api/migrate',{'rows':batch},token)[0]!=200;assert snapshot()==before_records, 'Rejected migration changed stored records'
 staff=a.login('staff-first');denied=a.request('/api/migrate',{'rows':[]},staff);assert denied[0]==403,denied

def ru003(a):
 for payload in [{'user_id':'staff-first','centre_id':'second','pin':'1357'},{'user_id':'staff-first','centre_id':'first','pin':'wrong'},{'user_id':'missing','centre_id':'first','pin':'1357'}]:assert a.request('/login',payload)[0]==403
 first=a.ok('/login',{'user_id':'staff-first','centre_id':'first','pin':'1357'});second=a.ok('/login',{'user_id':'staff-first','centre_id':'first','pin':'1357'});assert isinstance(first['token'],str) and bool(first['token']) and first['token']!=second['token'] and all(first['user'].get(k)==v for k,v in {'id':'staff-first','role':'staff','centre_id':'first'}.items())
 # Inspect actual stored user documents without prescribing credential field names,
 # session collection layout, or token encoding. Cryptographic strength requires
 # the separate non-scoring credential audit; these observations do not prove it.
 stored=a.inspect("console.log(JSON.stringify(await db.collection('users').find({}).toArray()));")
 def leaves(value):
  if isinstance(value,dict):return [v for x in value.values() for v in leaves(x)]
  if isinstance(value,list):return [v for x in value for v in leaves(x)]
  return [value]
 assert all(str(value)!='1357' for value in leaves(stored)), 'Plaintext PIN stored'
 # Recognize actual scrypt material by independently recomputing the documented
 # starter KDF, rather than classifying arbitrary long metadata as a secret.
 # Alternative credential schemes remain subject to the separate security audit.
 private_values=set(a.inspect("const crypto=require('node:crypto');const collect=x=>Array.isArray(x)?x.flatMap(collect):x&&typeof x==='object'?Object.values(x).flatMap(collect):typeof x==='string'?[x]:[];const secrets=new Set();for(const u of await db.collection('users').find({}).toArray()){const values=collect(u);for(const salt of values.filter(x=>x.length>=16&&x.length<=512)){const digest=crypto.scryptSync('1357',salt,32);for(const encoding of ['hex','base64','base64url']){const encoded=digest.toString(encoding);if(values.includes(encoded)){secrets.add(salt);secrets.add(encoded);}}}}console.log(JSON.stringify([...secrets]));"))
 for response in [first,second]:
  values=leaves(response)
  assert '1357' not in [str(v) for v in values] and not private_values.intersection(v for v in values if isinstance(v,str)), 'Private authentication material returned'
 # A valid session must actually work and survive the documented restart.
 assert a.ok('/api/records?module=daily_chart',token=first['token'])==[]
 assert a.request('/api/records?module=daily_chart',token='unknown')[0]==403
 a.close();restarted=App(a.mongo,a.root,a.dbname)
 try:
  assert restarted.ok('/api/records?module=daily_chart',token=first['token'])==[]
  restarted.login('staff-first')
 finally:restarted.close()

def ru004(a):
 admin=a.seed();staff=a.login('staff-first');parent=a.login('parent-first');assert {r['id'] for r in a.ok('/api/records?module=daily_chart',token=staff)}=={'legacy-a','legacy-b'};assert [r['id'] for r in a.ok('/api/records?module=daily_chart',token=parent)]==['legacy-a']
 assert a.request('/api/records?module=incident',token=parent)[0]==403 and a.request('/api/records?module=daily_chart&child_id=child-b',token=parent)[0]==403
 action={'id':'created','module':'attendance','centre_id':'first','child_id':'child-a','data':{'note':'Synthetic attendance'}};a.ok('/api/records',action,staff);assert len(a.ok('/api/records?module=attendance',token=staff))==1
 for suffix in ('','&child_id=child-a','&child_id=child-b'):
  assert a.request('/api/records?module=attendance'+suffix,token=parent)[0]==403,'Parents cannot read attendance, including their linked child'
 assert not a.ok('/api/parent-view?child_id=child-a',token=parent).get('attendance'),'Parent aggregate exposes no attendance records'
 before_records=a.inspect("console.log(JSON.stringify(await db.collection('records').find({}).sort({_id:1}).toArray()));")
 for payload,token in [({**action,'id':'bad','centre_id':'second','child_id':'child-c','role':'admin','actor_id':'admin'},staff),({**action,'id':'bad'},parent)]:
  assert a.request('/api/records',payload,token)[0]==403
  assert a.inspect("console.log(JSON.stringify(await db.collection('records').find({}).sort({_id:1}).toArray()));")==before_records, 'Denied record creation changed storage'
 result=subprocess.run([NODE,str(TESTS/'portal_probe.cjs'),a.url],env={**os.environ,'HOME':str(a.root/'home'),'PORTAL_BROWSER_LAUNCHER':str(PUBLIC/'browser_launch.py')},capture_output=True,text=True,timeout=30)
 if result.returncode==2:raise InfrastructureError('Protected browser startup failed: '+result.stderr[-1500:])
 assert result.returncode==0,result.stderr;browser=json.loads(result.stdout);assert browser['visible_records']==['curriculum-a'] and browser['create_hidden'],browser


def ru005(a):
 a.seed();parent=a.login('parent-first');staff=a.login('staff-first');other=a.login('staff-second','second');view=a.ok('/api/parent-view?child_id=child-a',token=parent);assert [r['id'] for r in view['daily_chart']]==['legacy-a'] and [r['id'] for r in view['curriculum']]==['curriculum-a']
 for child in ['child-b','child-c','missing']:assert a.request('/api/parent-view?child_id='+child,token=parent)[0]==403
 message={'message_id':'m','recipient_id':'staff-first','text':'Synthetic parent message','sender_id':'admin'};assert a.ok('/api/messages',message,parent).get('duplicate') is False;assert a.ok('/api/messages',message,parent).get('duplicate') is True;messages=a.ok('/api/messages',token=staff);assert len(messages)==1 and messages[0]['sender_id']=='parent-first' and a.ok('/api/messages',token=other)==[]
 before_messages=a.inspect("console.log(JSON.stringify(await db.collection('messages').find({}).sort({_id:1}).toArray()));")
 assert a.request('/api/messages',{**message,'text':'Conflict'},parent)[0]==409
 assert a.inspect("console.log(JSON.stringify(await db.collection('messages').find({}).sort({_id:1}).toArray()));")==before_messages
 for recipient in ['staff-second','missing']:
  assert a.request('/api/messages',{**message,'message_id':'bad','recipient_id':recipient},parent)[0]!=200
  assert a.inspect("console.log(JSON.stringify(await db.collection('messages').find({}).sort({_id:1}).toArray()));")==before_messages, 'Denied message changed storage'
 assert len(a.ok('/api/messages',token=parent))==1

def main():
 missing=[p.name for p in [TESTS/'input_probe.cjs',TESTS/'portal_probe.cjs',PUBLIC/'browser_launch.py',PUBLIC/'mongo_control.cjs'] if not p.is_file()]
 if missing:return {'harness_ok':False,'error':'Missing benchmark helper: '+', '.join(missing),'results':[]}
 if not os.environ.get('MONGOD_BIN') or not Path(os.environ['MONGOD_BIN']).is_file():return {'harness_ok':False,'error':'Pinned local MongoDB executable unavailable','results':[]}
 rows_out=[]
 with tempfile.TemporaryDirectory(prefix='sweclar-portal-') as temp:
  root=Path(temp);root.chmod(0o755);mongo=None
  try:
   mongo=Mongo(root)
   for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
    a=None;gate=root/f'gate-{i}';gate.mkdir()
    try:
     a=App(mongo,gate,f'sweclar_gate_{i}');test(a);row={'ru_id':f'RU-{i:03}','passed':True}
    except InfrastructureError as e:
     return {'harness_ok':False,'error':str(e),'results':rows_out}
    except subprocess.TimeoutExpired as e:
     return {'harness_ok':False,'error':'Unattributed evaluator subprocess timeout; reproduce before scoring','results':rows_out}
    except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2200:]}
    finally:
     if a:a.close()
    rows_out.append(row)
  except Exception as e:return {'harness_ok':False,'error':'MongoDB fixture: '+str(e),'results':rows_out}
  finally:
   if mongo:mongo.close()
   for project in root.glob('gate-*/project'):
    subprocess.run([sys.executable,'-c','import shutil,sys;from pathlib import Path;[(shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()) for p in Path(sys.argv[1]).iterdir()]',str(project)],user=1000,group=1000,extra_groups=[],check=True)
   for home in root.glob('gate-*/home'):
    subprocess.run([sys.executable,'-c','import shutil,sys;from pathlib import Path;[(shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()) for p in Path(sys.argv[1]).iterdir()]',str(home)],user=1000,group=1000,extra_groups=[],check=True)
 return {'harness_ok':True,'results':rows_out}
if __name__=='__main__':print(json.dumps(main()))
