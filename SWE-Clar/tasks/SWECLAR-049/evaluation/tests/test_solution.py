from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json,sqlite3,subprocess,sys,urllib.request,urllib.error
from conftest import load_solution

def action(m,db,kind,**fields):return m.process_mentor_event(str(db),{'type':kind,**fields})
def rows(db,query,params=()):
    with sqlite3.connect(db) as c:return c.execute(query,params).fetchall()
def snapshot(m,db):return action(m,db,'snapshot')['result']
def intake(m,db,role='mentor',email='synthetic@example.test'):return action(m,db,role+'_intake',email=email,name='Synthetic person')['result']

@contextmanager
def server(m,db):
    script=Path(m.__file__).parent/'server.py';process=subprocess.Popen([sys.executable,str(script),'--db',str(db),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,user=1000,group=1000,extra_groups=[],umask=0,env={'PATH':__import__('os').environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    try:
        line=process.stdout.readline();assert line,'server did not start';port=json.loads(line)['port'];yield f'http://127.0.0.1:{port}'
    finally:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        errors=process.stderr.read()
        if errors:print(errors)

def post(base,event):
    req=urllib.request.Request(base+'/events',data=json.dumps(event).encode(),headers={'Content-Type':'application/json'})
    try:response=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5)
    except urllib.error.HTTPError as error:response=error
    with response:return response.status,json.loads(response.read())


class InfrastructureError(RuntimeError):pass

@contextmanager
def fixture_db(path):
 class Fixture:
  def execute(self,sql,params=()):return self.executemany(sql,[params])
  def executemany(self,sql,params):
   script="import json,sqlite3,sys; r=json.load(sys.stdin); c=sqlite3.connect(r['path']); c.executemany(r['sql'],r['params']); c.commit(); c.close()"
   p=subprocess.run([sys.executable,'-I','-c',script],input=json.dumps({'path':str(path),'sql':sql,'params':params}),capture_output=True,text=True,timeout=10,user=1000,group=1000,extra_groups=[])
   if p.returncode:raise InfrastructureError('Fixture SQL failed: '+p.stderr)
 yield Fixture()

def error(out):assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
def test_ru_001_http_persistence_errors(tmp_path):
 m=load_solution();db=tmp_path/'one.sqlite';event={'type':'mentor_intake','email':'x@example.test','name':' X '}
 with server(m,db) as base:
  code,out=post(base,event);assert code==200;uid=out['result']['user_id'];assert json.load(urllib.request.urlopen(base+'/health'))['ok']
 assert db.read_bytes().startswith(b'SQLite format 3') and rows(db,'SELECT email,name FROM users WHERE user_id=?',(uid,))==[('x@example.test','X')]
 before=snapshot(m,db)
 with server(m,db) as base:
  code,out=post(base,{'type':'snapshot'});assert code==200 and out['result']==before
  for value in [None,[],4,{'type':'unknown'}]:
   code,out=post(base,value);assert code==400;error(out)
  req=urllib.request.Request(base+'/events',data=b'{broken')
  try:urllib.request.urlopen(req,timeout=5);assert False
  except urllib.error.HTTPError as ex:assert ex.code==400;error(json.load(ex))
 assert snapshot(m,db)==before

def test_ru_002_identity_names_concurrent(tmp_path):
 m=load_solution();db=tmp_path/'two.sqlite';a=intake(m,db,email=' X@Example.test ')
 replayed=action(m,db,'mentor_intake',email='x@example.test')['result']
 assert all(replayed[k]==a[k] for k in ['user_id','profile_id','role'])
 for value in [None,3,[],{}]:
  action(m,db,'mentor_intake',email='x@example.test',name=value);assert rows(db,'SELECT name FROM users')==[('Synthetic person',)]
 action(m,db,'mentor_intake',email='x@example.test',name='  ');assert rows(db,'SELECT name FROM users')==[('',)]
 b=intake(m,db,'mentee','x@example.test');assert b['user_id']==a['user_id'] and b['profile_id']!=a['profile_id']
 before=snapshot(m,db)
 for value in ['',None,'missing-at','a@@b','a @b','@b','a@','a@b\nc',5]:
  error(action(m,db,'mentor_intake',email=value));assert snapshot(m,db)==before
 with server(m,db) as base:
  with ThreadPoolExecutor(max_workers=6) as pool:response=list(pool.map(lambda _:post(base,{'type':'mentor_intake','email':'z@example.test'}),range(10)))
  assert all(code==200 for code,out in response);assert len({out['result']['profile_id'] for code,out in response})==1
 assert len(rows(db,'SELECT * FROM users'))==2 and len(rows(db,'SELECT * FROM profiles'))==3

def seed(m,db):
 snapshot(m,db)
 with fixture_db(db) as c:
  c.executemany('INSERT INTO users(user_id,email) VALUES (?,?)',[('u','u@example.test'),('v','v@example.test'),('w','w@example.test')])
  c.executemany('INSERT INTO profiles(profile_id,user_id,role) VALUES (?,?,?)',[('z-mentor','u','mentor'),('a-mentor','u','mentor'),('z-mentee','v','mentee'),('a-mentee','v','mentee'),('untouched','w','mentor')])
  c.executemany('INSERT INTO matches(match_id,mentor_id,mentee_id,status) VALUES (?,?,?,?)',[('z-match','a-mentor','a-mentee','accepted'),('a-match','z-mentor','z-mentee','suggested')])
  c.executemany('INSERT INTO outbox(notice_id,match_id) VALUES (?,?)',[('z-notice','a-match'),('a-notice','z-match')])

def test_ru_003_cleanup_survivors_foreign_keys_atomicity(tmp_path):
 m=load_solution();db=tmp_path/'three.sqlite';seed(m,db)
 out=action(m,db,'cleanup_duplicates');assert out['result']['status']=='deduplicated'
 assert rows(db,'SELECT profile_id FROM profiles ORDER BY sequence')==[('z-mentor',),('z-mentee',),('untouched',)]
 assert rows(db,'SELECT match_id,mentor_id,mentee_id,status FROM matches')==[('z-match','z-mentor','z-mentee','accepted')]
 assert rows(db,'SELECT notice_id,match_id FROM outbox')==[('z-notice','z-match')];assert rows(db,'PRAGMA foreign_key_check')==[]
 before=snapshot(m,db);assert action(m,db,'cleanup_duplicates')['result']['status']=='deduplicated';assert snapshot(m,db)==before
 action(m,db,'stabilize_automations')
 for kind,email,pid in [('legacy_mentor_intake','U@example.test','z-mentor'),('legacy_mentee_intake','V@example.test','z-mentee')]:assert action(m,db,kind,email=email)['result']['profile_id']==pid
 for i,sql in enumerate(["INSERT INTO profiles(profile_id,user_id,role) VALUES ('orphan','missing','mentor')","UPDATE matches SET mentor_id='z-mentee'","UPDATE matches SET mentee_id='missing'","INSERT INTO outbox(notice_id,match_id) VALUES ('orphan','missing')"]):
  broken=tmp_path/f'bad{i}.sqlite';seed(m,broken)
  with fixture_db(broken) as c:c.execute(sql)
  before=snapshot(m,broken);error(action(m,broken,'cleanup_duplicates'));assert snapshot(m,broken)==before
 empty=tmp_path/'empty.sqlite';assert action(m,empty,'cleanup_duplicates')['result']['status']=='deduplicated'

def test_ru_004_settings_preservation(tmp_path):
 m=load_solution();db=tmp_path/'four.sqlite';snapshot(m,db)
 with fixture_db(db) as c:
  c.execute("INSERT INTO automations VALUES ('unrelated-on',1)");c.execute("INSERT INTO automations VALUES ('unrelated-off',0)");c.execute("UPDATE automations SET enabled=0 WHERE automation_id='canonical_matching'")
 before=dict(rows(db,'SELECT automation_id,enabled FROM automations'));out=action(m,db,'stabilize_automations');assert 'result' in out
 expected={**before,**{k:0 for k in ['legacy_mentor','legacy_mentee','duplicate_match','duplicate_notice']}}
 assert dict(rows(db,'SELECT automation_id,enabled FROM automations'))==expected
 action(m,db,'stabilize_automations');assert dict(rows(db,'SELECT automation_id,enabled FROM automations'))==expected
 with fixture_db(db) as c:
  c.execute("DELETE FROM automations WHERE automation_id IN ('legacy_mentor','canonical_matching')")
 expected={key:value for key,value in expected.items() if key not in ('legacy_mentor','canonical_matching')}
 for _ in range(2):
  action(m,db,'stabilize_automations')
  assert dict(rows(db,'SELECT automation_id,enabled FROM automations'))==expected

def test_ru_005_match_and_outbox_durability_missing_links(tmp_path):
    m=load_solution();db=tmp_path/'workflow.sqlite';mentor=intake(m,db);mentee=intake(m,db,'mentee','other@example.test')
    event={'type':'create_match','mentor_id':mentor['profile_id'],'mentee_id':mentee['profile_id']}
    with server(m,db) as base:
        with ThreadPoolExecutor(max_workers=6) as pool:matches=list(pool.map(lambda _:post(base,event)[1]['result']['match_id'],range(8)))
        assert len(set(matches))==1;mid=matches[0]
        with ThreadPoolExecutor(max_workers=6) as pool:notices=list(pool.map(lambda _:post(base,{'type':'notify_match','match_id':mid})[1]['result']['notice_id'],range(8)))
        assert len(set(notices))==1
    with server(m,db) as base:
        assert post(base,event)[1]['result']['match_id']==mid
        assert post(base,{'type':'notify_match','match_id':mid})[1]['result']['notice_id']==notices[0]
    before=snapshot(m,db)
    assert 'error' in action(m,db,'create_match',mentor_id='missing',mentee_id=mentee['profile_id'])
    assert 'error' in action(m,db,'create_match',mentor_id=mentee['profile_id'],mentee_id=mentor['profile_id'])
    assert 'error' in action(m,db,'notify_match',match_id='missing')
    assert snapshot(m,db)==before and len(before['matches'])==len(before['outbox'])==1
