"""Independent HTTP, real-file, database and browser assertions for frozen hiring RUs."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import base64,concurrent.futures,csv,hashlib,io,json,os,sys,time,traceback,urllib.request,urllib.error
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode,urlparse
sys.path.insert(0,'/public_tests')
from public_support import application,request,database_rows,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
T=1704196800000;M=60000;D=86400000

def fixture():
 return {'clock_ms':T,'users':[{'id':u,'name':name,'role':role,'bio':'Literal <b>profile</b>','password':'private-fixture-pass'} for u,name,role in [('e-one','Synthetic One <team>','employer'),('e-two','Synthetic Two','employer'),('w-one','Synthetic Applicant One','employee'),('w-two','Synthetic Applicant Two','employee')]],'jobs':[{'job_id':j,'employer_id':e,'title':title,'description':'Build literal <img src=x onerror=alert(1)> content.','category':category,'location':'Remote','active':active} for j,e,title,category,active in [('j-one','e-one','Straße engineering','Web',True),('j-two','e-two','Data tooling','Data',True),('j-closed','e-one','Closed opportunity','Web',False)]],'relationships':[],'resumes':[],'applications':[],'interviews':[],'views':[]}

def login(app,u='w-one'):return request(app,'/api/login',body={'id':u,'password':'private-fixture-pass'},method='POST')['token']
def tokens(app):return {u:login(app,u) for u in ['e-one','e-two','w-one','w-two']}
def get(app,path,token,**query):return request(app,'/api/'+path+('?' +urlencode(query) if query else ''),token)
def post(app,path,token,body,status=200):return request(app,'/api/'+path,token,body,'POST',status=status)
def put(app,path,token,body,status=200):return request(app,'/api/'+path,token,body,'PUT',status=status)
def project(rows,keys):return [{k:r[k] for k in keys} for r in rows]
def ids(rows,key):return [r[key] for r in rows]
def resume(ident='cv-one',content=b'Independent synthetic CV.\n',name='CV.txt'):return {'resume_id':ident,'filename':name,'content_base64':base64.b64encode(content).decode()}
def application_body(ident='a-one',job='j-one',cv=None):return {'application_id':ident,'job_id':job,'resume_id':cv}
def slot(appid='a-one',ident='i-one',start=T+M,end=T+2*M):return {'application_id':appid,'interview_id':ident,'start_ms':start,'end_ms':end}
def change_job(row,**changes):return {k:changes.get(k,row[k]) for k in ['job_id','title','description','category','location','active']}

def raw_status(app,path,token,body):
 req=urllib.request.Request(app.url+'/api/'+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 try:r=urllib.request.urlopen(req,timeout=15)
 except urllib.error.HTTPError as error:r=error
 with r:return r.status,json.load(r)

def sign_in(page,app,user='w-one',navigate=True):
 if navigate:page.goto(app.url)
 page.locator('#account').fill(user);page.locator('#password').fill('private-fixture-pass');page.locator('#login-form button').click();expect(page.locator('[data-profile-id]')).to_have_count(4);expect(page.locator('#identity')).to_contain_text(next(u['name'] for u in fixture()['users'] if u['id']==user))

def agenda_time(text, milliseconds):
 dt=datetime.fromtimestamp(milliseconds/1000,timezone.utc)
 sep=r'\s*[-/.]\s*';name=rf'(?:{dt:%B}|{dt:%b})'
 date=rf'(?<!\d)(?:{dt.year}{sep}0?{dt.month}{sep}0?{dt.day}|0?{dt.day}{sep}0?{dt.month}{sep}{dt.year}|0?{dt.month}{sep}0?{dt.day}{sep}{dt.year}|0?{dt.day}\s+{name}\s*,?\s*{dt.year}|{name}\s+0?{dt.day},?\s+{dt.year})(?!\d)'
 clock=rf'(?:0?{dt.hour%12 or 12}:{dt.minute:02d}(?::00(?:\.0+)?)?\s*{"AM" if dt.hour<12 else "PM"}\b|0?{dt.hour}:{dt.minute:02d}(?::00(?:\.0+)?)?(?![\d:.]|\s*[AP]M\b))'
 return bool(re.search(r'\b(?:UTC|GMT)\b|\dZ\b|\+00:?00',text,re.I) and re.search(date,text,re.I) and re.search(r'(?<![\d:])'+clock,text,re.I))

def agenda_matches(page, rows, seed):
 expected=[r['interview_id'] for r in sorted(rows,key=lambda r:(r['start_ms'],r['interview_id']))]
 expect(page.locator('[data-interview-id]')).to_have_count(len(rows))
 assert page.locator('[data-interview-id]').evaluate_all('(ns)=>ns.map(n=>n.dataset.interviewId)')==expected
 for row in rows:
  text=page.locator('[data-interview-id='+json.dumps(row['interview_id'])+']').inner_text()
  job=next(j for j in seed['jobs'] if j['job_id']==row['job_id'])
  assert job['job_id'] in text or job['title'] in text, 'Agenda omitted job'
  for uid in row['participants']:
   person=next(u for u in seed['users'] if u['id']==uid)
   assert uid in text or person['name'] in text, 'Agenda omitted participant'
  assert agenda_time(text,row['start_ms']) and agenda_time(text,row['end_ms']), 'Agenda omitted readable UTC interval'

class HeldGroup:
 def __init__(self,page,paths):
  self.page=page;self.paths=set(paths);self.held={};page.route('**/api/*',self.capture)
 def capture(self,route):
  path=urlparse(route.request.url).path
  if path in self.paths and path not in self.held:self.held[path]=(route,route.fetch())
  else:route.continue_()
 def wait(self):
  until=time.monotonic()+5
  while len(self.held)<len(self.paths) and time.monotonic()<until:self.page.wait_for_timeout(20)
  assert len(self.held)==len(self.paths),'Required successful requests were not made'
 def release(self):
  for route,response in self.held.values():assert response.status==200;route.fulfill(response=response)
  self.page.wait_for_timeout(150);self.page.unroute('**/api/*',self.capture)

def check_1():
 f=fixture()
 with application(f) as app:
  for body in [{'id':'w-one','password':'wrong'},{'id':'missing','password':'private-fixture-pass'}]:request(app,'/api/login',body=body,method='POST',status=401)
  ts=tokens(app);token=ts['w-one'];another=login(app)
  for bad in [None,'w-one','e-one','forged']:
   for ep in ['me','profiles','relationships','jobs','applications','calendar']:request(app,'/api/'+ep,bad,status=401)
  response=get(app,'me',token);assert response['clock_ms']==T and response['user']['id']=='w-one' and response['user']['role']=='employee'
  for ep in ['me','profiles','relationships']:
   s=json.dumps(get(app,ep,token));assert all(v not in s for v in ['private-fixture-pass','password_hash',ts['e-one'],ts['e-two'],ts['w-two'],another])
  for body in [{'name':'Changed','bio':'x','role':'employer'},{'name':'Changed','bio':'x','id':'e-one'},{'name':True,'bio':''},{'name':' ','bio':''},{'name':'x'*121,'bio':''},{'name':'x','bio':'y'*2001}]:put(app,'profile',token,body,400)
  assert get(app,'me',token)['user']['name']==f['users'][2]['name']
  post(app,'logout',token,{});request(app,'/api/me',token,status=401);assert get(app,'me',another)['user']['id']=='w-one'
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True)
   try:
    page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));sign_in(page,app)
    assert page.locator('#profiles b,#profiles img').count()==0
    for width,height in [(390,844),(1280,900)]:page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    held=HeldGroup(page,['/api/me','/api/profiles','/api/relationships']);page.locator('#refresh').click();held.wait();page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden();assert page.locator('#identity').inner_text()==''
    sign_in(page,app,'e-two',navigate=False)
    page.evaluate("()=>{window.flashes=[];window.watcher=new MutationObserver(()=>{const text=document.getElementById('identity').textContent;if(text.includes('Applicant One'))flashes.push(text);});watcher.observe(document.getElementById('identity'),{subtree:true,childList:true,characterData:true});}")
    held.release();assert page.evaluate('flashes')==[];expect(page.locator('#identity')).to_contain_text('Synthetic Two');assert not errors,errors
   finally:browser.close()

def check_2():
 f=fixture()
 with application(f) as app:
  ts=tokens(app);profile={'name':'  New <img src=x> name  ','bio':'  <b>Untrimmed bio</b>  '};put(app,'profile',ts['w-one'],profile)
  assert get(app,'me',ts['w-one'])['user']['name']==profile['name'].strip();assert get(app,'me',ts['w-one'])['user']['bio']==profile['bio']
  assert get(app,'me',ts['e-one'])['user']['name']==f['users'][0]['name']
  for actor in ts:
   for target in ts:
    for kind in ['follow','connect']:
     expected=400 if actor==target else 200 if (kind=='follow' and target.startswith('e-')) or (kind=='connect' and actor.startswith('w-') and target.startswith('w-')) else 403
     body={'target_id':target,'kind':kind,'enabled':True};post(app,'relationships',ts[actor],body,expected)
     if expected==200:post(app,'relationships',ts[actor],body)
  stored=database_rows(app,'relationships');assert len(stored)==7
  for actor,token in ts.items():
   rows=get(app,'relationships',token)['relationships'];expected=sorted([r for r in stored if actor in [r['actor_id'],r['target_id']]],key=lambda r:(r['kind'],r['actor_id'],r['target_id']));assert project(rows,['actor_id','target_id','kind'])==project(expected,['actor_id','target_id','kind'])
  post(app,'relationships',ts['w-two'],{'target_id':'w-one','kind':'connect','enabled':False});post(app,'relationships',ts['w-two'],{'target_id':'w-one','kind':'connect','enabled':False})
  assert all(r['kind']!='connect' for r in get(app,'relationships',ts['w-one'])['relationships'])
  before=database_rows(app,'relationships')
  for body,status in [({'target_id':'missing','kind':'follow','enabled':True},404),({'target_id':'e-one','kind':'other','enabled':True},400),({'target_id':'e-one','kind':'follow','enabled':1},400),({'target_id':'e-one','kind':'follow','enabled':True,'actor_id':'e-two'},400)]:post(app,'relationships',ts['w-one'],body,status)
  assert database_rows(app,'relationships')==before
  app.stop();app.start();assert database_rows(app,'relationships')==before;assert get(app,'me',ts['w-one'])['user']['bio']==profile['bio']
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True)
   try:
    page=browser.new_page();sign_in(page,app,'e-one');page.locator('#profile-name').fill('Browser employer');page.locator('#profile-bio').fill('Browser <literal> biography');page.locator('#profile-save').click();expect(page.locator('[data-profile-id="e-one"]')).to_contain_text('Browser employer')
    page.locator('#relation-target').select_option('e-two');page.locator('#relation-kind').select_option('follow');page.locator('#relation-enabled').uncheck();page.locator('#relationship-save').click()
    # Directional removal preserves the opposite employer's follow.
    for _ in range(30):
     if not any(r['actor_id']=='e-one' and r['target_id']=='e-two' for r in database_rows(app,'relationships')):break
     page.wait_for_timeout(30)
    rows=database_rows(app,'relationships');assert not any(r['actor_id']=='e-one' and r['target_id']=='e-two' for r in rows);assert any(r['actor_id']=='e-two' and r['target_id']=='e-one' for r in rows)
   finally:browser.close()

def check_3():
 f=fixture();f['jobs'][0]['location']='Remote';f['jobs'][1]['location']='Remote'
 with application(f) as app:
  ts=tokens(app);a,b,w,z=(ts[u] for u in ['e-one','e-two','w-one','w-two'])
  assert ids(get(app,'jobs',w)['jobs'],'job_id')==['j-one','j-two'];assert ids(get(app,'jobs',a)['jobs'],'job_id')==['j-closed','j-one']
  assert ids(get(app,'jobs',w,q=' STRASSE ',category=' web ',location=' REMOTE ')['jobs'],'job_id')==['j-one']
  assert get(app,'jobs',w,q='Data',category='Web')['jobs']==[]
  create={'job_id':'j-new','title':'  Test title  ','description':'  Test <literal> description  ','category':' Web ','location':'Remote'}
  post(app,'jobs',w,create,403);created=post(app,'jobs',a,create)['job'];assert created['title']=='Test title' and created['active'] is True and created['employer_id']=='e-one'
  post(app,'jobs',a,create,409);put(app,'jobs',b,change_job(created,title='stolen'),403)
  for changes in [{'title':''},{'description':' '},{'category':1},{'location':'x'*81},{'active':1}]:put(app,'jobs',a,change_job(created,**changes),400)
  assert get(app,'job',a,job_id='j-new')['job']['title']=='Test title'
  post(app,'bookmarks',w,{'job_id':'j-new','enabled':True});post(app,'bookmarks',w,{'job_id':'j-new','enabled':True});assert len(database_rows(app,'bookmarks'))==1
  closed=put(app,'jobs',a,change_job(created,active=False))['job'];assert closed['active'] is False
  assert get(app,'bookmarks',w)['jobs'][0]['active'] is False
  before_bookmarks=database_rows(app,'bookmarks')
  bookmark_conflict=raw_status(app,'bookmarks',w,{'job_id':'j-new','enabled':True})
  # An already-enabled bookmark is an idempotent replay. The contract does
  # not order replay detection versus closed-job validation, so either a
  # successful no-op or a business rejection is valid; neither may mutate.
  assert bookmark_conflict[0] in (200,400,403,404,409,422)
  if bookmark_conflict[0]!=200:
   assert isinstance(bookmark_conflict[1].get('error',{}).get('code'),str) and bookmark_conflict[1]['error']['code']
  assert database_rows(app,'bookmarks')==before_bookmarks,'Closed bookmark replay changed state'
  post(app,'bookmarks',w,{'job_id':'j-new','enabled':False});assert database_rows(app,'bookmarks')==[]
  # In contrast, enabling a NEW bookmark on a closed job must be rejected.
  new_closed=raw_status(app,'bookmarks',w,{'job_id':'j-new','enabled':True})
  assert new_closed[0] in (400,403,404,409,422),'Closed job must reject a new bookmark'
  assert isinstance(new_closed[1].get('error',{}).get('code'),str) and new_closed[1]['error']['code']
  assert database_rows(app,'bookmarks')==[],'Rejected closed bookmark created a row'
  put(app,'jobs',a,change_job(created,active=True));request(app,'/api/job?job_id=j-closed',w,status=403)
  payload=resume(content='CV\n独立数据 <img>\n'.encode(),name='Resume.TXT');uploaded=post(app,'resumes',w,payload);data=base64.b64decode(payload['content_base64']);assert uploaded['resume']['size_bytes']==len(data) and uploaded['resume']['sha256']==hashlib.sha256(data).hexdigest();assert post(app,'resumes',w,payload)['duplicate'] is True
  for ident_,data,name in [('maximum',b'x'*262144,'A'*76+'.txt'),('minimum',b'x','a.txt')]:
   output=post(app,'resumes',w,resume(ident_,data,name));assert output['resume']['size_bytes']==len(data) and output['resume']['sha256']==hashlib.sha256(data).hexdigest();assert request(app,'/api/resume?resume_id='+ident_,w,raw=True).encode()==data
  for bad in [{**payload,'content_base64':base64.b64encode(x).decode()} for x in [b'',b'\xff',b'a\0b',b'a'*262145]]+[{**payload,'filename':n} for n in ['../CV.txt','/CV.txt','CV.pdf','a".txt','x'*81+'.txt']]+[{**payload,'content_base64':payload['content_base64']+'\n'}]:post(app,'resumes',w,bad,400)
  for token in [a,b,z]:request(app,'/api/resume?resume_id=cv-one',token,status=403)
  post(app,'resumes',a,payload,403);post(app,'resumes',z,payload,409);post(app,'resumes',w,resume(content=b'changed'),409)
  assert request(app,'/api/resume?resume_id=cv-one',w,raw=True).encode()==base64.b64decode(payload['content_base64'])
  post(app,'applications',z,application_body('bad-owner','j-one','cv-one'),403);post(app,'applications',w,application_body('bad-missing','j-one','absent'),403)
  body=application_body(cv='cv-one')
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:post(app,'applications',w,body),range(8)))
  assert sum(r['duplicate'] is False for r in results)==1 and sum(r['duplicate'] is True for r in results)==7
  post(app,'applications',w,application_body('second-id','j-one','cv-one'),409);post(app,'applications',w,application_body('a-one','j-two'),409)
  assert request(app,'/api/resume?resume_id=cv-one',a,raw=True).encode()==base64.b64decode(payload['content_base64']);request(app,'/api/resume?resume_id=cv-one',b,status=403)
  assert get(app,'applications',b)['applications']==[] and get(app,'applications',z)['applications']==[]
  original=get(app,'job',a,job_id='j-one')['job'];put(app,'jobs',a,change_job(original,active=False));assert post(app,'applications',w,body)['duplicate'] is True
  before_closed=database_rows(app,'applications')
  closed_status,closed_body=raw_status(app,'applications',z,application_body('closed-new','j-one'))
  assert closed_status in (400,403,404,409,422), 'An inactive job must reject new applications'
  assert isinstance(closed_body.get('error',{}).get('code'),str) and closed_body['error']['code']
  assert database_rows(app,'applications')==before_closed, 'Rejected application must not mutate storage'
  before={key:database_rows(app,key) for key in ['jobs','resumes','applications','bookmarks']};app.stop();app.start();assert all(database_rows(app,key)==rows for key,rows in before.items())
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True)
   try:
    page=browser.new_page(accept_downloads=True);sign_in(page,app,'w-two');page.locator('[data-job-id="j-two"] [data-action="open"]').click();expect(page.locator('#job-detail')).to_contain_text('Data tooling');assert page.locator('#job-detail img').count()==0
    content='Browser-owned CV\n\u00e9\n';page.locator('#resume-file').set_input_files({'name':'Browser Resume.txt','mimeType':'text/plain','buffer':content.encode()});page.locator('#resume-id').fill('cv-browser');page.locator('#upload-resume').click()
    # Observe the actual upload response before applying, without imposing success wording.
    for _ in range(50):
     if any(r['resume_id']=='cv-browser' for r in database_rows(app,'resumes')):break
     page.wait_for_timeout(30)
    assert any(r['resume_id']=='cv-browser' for r in database_rows(app,'resumes'))
    page.locator('#application-id').fill('a-browser');page.locator('#apply').click();expect(page.locator('[data-application-id="a-browser"]')).to_be_visible();page.locator('#logout').click();sign_in(page,app,'e-two',navigate=False)
    page.locator('[data-application-id="a-browser"] [data-action="select"]').click()
    with page.expect_download() as pending:page.locator('#download-resume').click()
    downloaded=pending.value;assert downloaded.suggested_filename=='Browser Resume.txt' and Path(downloaded.path()).read_bytes()==content.encode()
    for field,value in [('job-id','j-browser'),('job-title','Browser <b>job</b>'),('job-description','Independent browser-created description'),('job-category','Web'),('job-location','Remote')]:page.locator('#'+field).fill(value)
    page.locator('#job-save').click();expect(page.locator('#jobs [data-job-id="j-browser"]')).to_contain_text('Browser <b>job</b>');assert page.locator('#jobs [data-job-id="j-browser"] b').count()==0
    page.locator('[data-job-id="j-browser"] [data-action="open"]').click();expect(page.locator('#job-detail')).to_contain_text('Browser <b>job</b>');expect(page.locator('#job-title')).to_have_value('Browser <b>job</b>')
    page.locator('#job-title').fill('Edited through browser');page.locator('#job-active').uncheck();page.locator('#job-save').click();expect(page.locator('#jobs [data-job-id="j-browser"]')).to_contain_text('Edited through browser')
    assert get(app,'job',b,job_id='j-browser')['job']['active'] is False

   finally:browser.close()

def check_4():
 f=fixture();f['applications']=[application_body(a,j)|{'employee_id':w,'status':'applied'} for a,j,w in [('a-one','j-one','w-one'),('a-two','j-one','w-two'),('a-three','j-two','w-one'),('a-four','j-two','w-two')]]
 f['jobs'][0]['active']=False
 with application(f) as app:
  ts=tokens(app);a,b,w,z=(ts[u] for u in ['e-one','e-two','w-one','w-two'])
  for token,body in [(w,slot()),(b,slot()),(a,slot(appid='missing'))]:post(app,'interviews',token,body,403)
  for body in [slot(start=T-1),slot(start=T,end=T),slot(start=T,end=T+8*60*M+1),slot(start=True),slot(end='later')]:post(app,'interviews',a,body,400)
  result=post(app,'interviews',a,slot());assert result['duplicate'] is False;assert result['interview']['participants']==['e-one','w-one'];assert post(app,'interviews',a,slot())['duplicate'] is True
  before=database_rows(app,'interviews')
  for token,body in [(a,slot('a-two','employer-conflict')),(b,slot('a-three','worker-conflict')),(a,slot(ident='second-event')),(b,slot('a-three','i-one'))]:post(app,'interviews',token,body,409)
  assert database_rows(app,'interviews')==before
  post(app,'interviews',a,slot('a-two','adjacent',T+2*M,T+3*M));assert ids(get(app,'calendar',w)['interviews'],'interview_id')==['i-one'];assert get(app,'calendar',b)['interviews']==[]
  post(app,'reject',b,{'application_id':'a-one'},403);post(app,'reject',a,{'application_id':'a-one'});post(app,'reject',a,{'application_id':'a-one'});assert get(app,'calendar',w)['interviews']==[]
  post(app,'interviews',a,slot(),409);post(app,'interviews',b,slot('a-three','freed-slot'))
  assert ids(get(app,'calendar',w)['interviews'],'interview_id')==['freed-slot']
  before=database_rows(app,'interviews');app.stop();app.start();assert database_rows(app,'interviews')==before
 with application(f) as app:
  ts=tokens(app);a=ts['e-one'];bodies=[slot('a-one','racing-one'),slot('a-two','racing-two')]
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda body:raw_status(app,'interviews',a,body),bodies))
  assert sorted(code for code,_ in results)==[200,409];assert len(database_rows(app,'interviews'))==1
  assert sorted(r['status'] for r in database_rows(app,'applications') if r['job_id']=='j-one')==['applied','scheduled']
 with application(f) as app:
  ts=tokens(app);post(app,'interviews',ts['e-one'],slot(start=T,end=T+8*60*M));post(app,'reject',ts['e-one'],{'application_id':'a-one'})
  post(app,'interviews',ts['e-two'],slot('a-four','later-slot',T+3*60*M,T+4*60*M))
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True)
   try:
    page=browser.new_page();sign_in(page,app,'e-two');page.locator('[data-application-id="a-three"] [data-action="select"]').click();page.locator('#interview-id').fill('browser-slot');page.locator('#interview-start').fill('2024-01-02T13:00:00.000Z');page.locator('#interview-end').fill('2024-01-02T14:00:00.000Z');page.locator('#schedule').click();expect(page.locator('[data-interview-id="browser-slot"]')).to_be_visible()
    agenda_matches(page,get(app,'calendar',ts['e-two'])['interviews'],f)
    page.locator('#logout').click();sign_in(page,app,'w-one',navigate=False);expect(page.locator('[data-interview-id="browser-slot"]')).to_be_visible();assert page.locator('#schedule').is_hidden() or page.locator('#schedule').is_disabled()
    agenda_matches(page,get(app,'calendar',ts['w-one'])['interviews'],f)
    page.locator('#logout').click();sign_in(page,app,'e-two',navigate=False);page.locator('[data-application-id="a-three"] [data-action="select"]').click();page.locator('#reject').click();expect(page.locator('[data-interview-id="browser-slot"]')).to_have_count(0)
    assert not get(app,'calendar',ts['w-one'])['interviews']
   finally:browser.close()

def check_5():
 f=fixture()
 with application(f) as app:
  ts=tokens(app);a,b,w,z=(ts[u] for u in ['e-one','e-two','w-one','w-two'])
  row={'event_id':'one','job_id':'j-one','timestamp_ms':T-D}
  post(app,'views',a,row,403)
  for bad in [{**row,'timestamp_ms':v} for v in [True,-1,1.5,253402300800000]]+[{**row,'viewer_id':'w-two'}]:post(app,'views',w,bad,400)
  post(app,'views',w,{**row,'job_id':'j-closed'},404)
  events=[(w,'one',T-D),(w,'two',T),(z,'two',T),(w,'future',T+1),(z,'origin',0),(w,'last',253402300799999)]
  for token,eid,stamp in events:post(app,'views',token,{'event_id':eid,'job_id':'j-one','timestamp_ms':stamp})
  assert post(app,'views',w,row)['duplicate'] is True;post(app,'views',w,{**row,'timestamp_ms':T},409)
  full=get(app,'analytics',a,job_id='j-one');assert full['views']==6 and full['unique_viewers']==2;assert [(r['day'],r['views'],r['unique_viewers']) for r in full['by_day']]==[('1970-01-01',1,1),('2024-01-01',1,1),('2024-01-02',3,2),('9999-12-31',1,1)]
  result=get(app,'analytics',a,job_id='j-one',start_ms=T-D,end_ms=T);assert result['views']==3 and result['unique_viewers']==2;assert [(r['day'],r['views']) for r in result['by_day']]==[('2024-01-01',1),('2024-01-02',2)]
  assert get(app,'analytics',a,job_id='j-one',start_ms=T,end_ms=T)['views']==2
  for token,j in [(b,'j-one'),(w,'j-one'),(a,'missing')]:
   for ep in ['analytics','analytics.csv']:request(app,'/api/'+ep+'?job_id='+j,token,status=403)
  for query in [{'job_id':'j-one','start_ms':T},{'job_id':'j-one','start_ms':T+1,'end_ms':T},{'job_id':'j-one','start_ms':'true','end_ms':T}]:request(app,'/api/analytics?'+urlencode(query),a,status=400)
  csv_text=request(app,'/api/analytics.csv?'+urlencode({'job_id':'j-one','start_ms':T-D,'end_ms':T}),a,raw=True);reader=csv.DictReader(io.StringIO(csv_text));assert reader.fieldnames==['day','views','unique_viewers'];assert [int(r['views']) for r in reader]==[1,2]
  old=get(app,'job',a,job_id='j-one')['job'];put(app,'jobs',a,change_job(old,active=False));assert post(app,'views',w,row)['duplicate'] is True;post(app,'views',w,{**row,'event_id':'closed-new'},404);assert get(app,'analytics',a,job_id='j-one')['views']==6
  app.stop();app.start();assert get(app,'analytics',a,job_id='j-one')['views']==6
 with application(f) as app:
  ts=tokens(app);w,a=ts['w-one'],ts['e-one'];post(app,'views',w,{'event_id':'earlier','job_id':'j-one','timestamp_ms':T-D})
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True)
   try:
    page=browser.new_page(accept_downloads=True);sign_in(page,app);captured=[];successful=[]
    page.on('response',lambda r:successful.append(r.status) if urlparse(r.url).path=='/api/views' and r.status==200 else None)
    def lost_ack(route):
     captured.append(json.loads(route.request.post_data))
     if len(captured)==1:response=route.fetch();assert response.status==200;route.fulfill(status=503,content_type='application/json',body='{"error":{"code":"response_lost"}}')
     else:route.continue_()
    page.route('**/api/views',lost_ack);page.locator('[data-job-id="j-one"] [data-action="open"]').click()
    deadline=time.monotonic()+5
    while not successful and not page.locator('#view-retry').is_enabled() and time.monotonic()<deadline:page.wait_for_timeout(20)
    if not successful:
     expect(page.locator('#view-retry')).to_be_enabled();page.locator('#view-retry').click()
    deadline=time.monotonic()+5
    while not successful and time.monotonic()<deadline:page.wait_for_timeout(20)
    assert successful and len(captured)>=2
    assert all(row==captured[0] for row in captured),'Any retry must retain the same full view event'
    assert len(database_rows(app,'views'))==2
    boundary=len(captured);page.locator('[data-job-id="j-one"] [data-action="open"]').click()
    deadline=time.monotonic()+5
    while (len(captured)<=boundary or len(database_rows(app,'views'))<3) and time.monotonic()<deadline:page.wait_for_timeout(20)
    assert len(captured)>boundary and captured[boundary]['event_id']!=captured[0]['event_id']
    assert all(row==captured[boundary] for row in captured[boundary:]) and len(database_rows(app,'views'))==3
    page.locator('#logout').click();sign_in(page,app,'e-one',navigate=False);page.locator('#analytics-job').select_option('j-one');page.locator('#analytics-load').click();expect(page.locator('#view-chart rect[data-day]')).to_have_count(2)
    heights=page.locator('#view-chart rect[data-day]').evaluate_all('(nodes)=>nodes.map(n=>n.getBoundingClientRect().height)');assert heights[0]>0 and abs(heights[1]/heights[0]-2)<.01
    with page.expect_download() as pending:page.locator('#analytics-download').click()
    assert [int(r['views']) for r in csv.DictReader(io.StringIO(Path(pending.value.path()).read_text()))]==[1,2]
    held=HeldGroup(page,['/api/analytics']);page.locator('#analytics-load').click();held.wait();page.locator('#analytics-job').select_option('j-closed');page.locator('#analytics-load').click();expect(page.locator('#view-chart rect[data-day]')).to_have_count(0)
    page.evaluate("()=>{window.chartFlashes=[];window.chartObserver=new MutationObserver(()=>{if(document.querySelectorAll('#view-chart rect[data-day]').length)chartFlashes.push(true);});chartObserver.observe(document.getElementById('view-chart'),{subtree:true,childList:true});}")
    held.release();assert page.evaluate('chartFlashes')==[],'Late old-job result rendered chart';page.evaluate('chartObserver.disconnect()')
    page.locator('#analytics-job').select_option('j-one');page.locator('#analytics-load').click();expect(page.locator('#view-chart rect[data-day]')).to_have_count(2)
    held=HeldGroup(page,['/api/analytics']);page.locator('#analytics-load').click();held.wait();page.locator('#analytics-start').fill('2024-01-02T12:00:00.000Z');page.locator('#analytics-end').fill('2024-01-02T12:00:00.000Z');page.locator('#analytics-load').click();expect(page.locator('#view-chart rect[data-day]')).to_have_count(1)
    page.evaluate("()=>{window.periodFlashes=[];window.periodObserver=new MutationObserver(()=>{if(document.querySelector('#view-chart rect[data-day=\"2024-01-01\"]'))periodFlashes.push(true);});periodObserver.observe(document.getElementById('view-chart'),{subtree:true,childList:true});}")
    held.release();assert page.evaluate('periodFlashes')==[],'Late old-period result rendered chart';page.evaluate('periodObserver.disconnect()')
    for width,height in [(390,844),(1280,900)]:page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   finally:browser.close()

def main():
 results=[];infra=[];chosen=os.environ.get('HIRING_GATE')
 for i,test in enumerate([check_1,check_2,check_3,check_4,check_5],1):
  if chosen and chosen!=str(i):continue
  try:test();result={'ru_id':f'RU-{i:03d}','passed':True}
  except (AssertionError,CandidateFailure,BrowserTimeout,KeyError,IndexError) as e:traceback.print_exc(file=sys.stderr);result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(e)[-1800:] or type(e).__name__}
  except Exception as e:
   traceback.print_exc(file=sys.stderr);infra.append(f'RU-{i:03d}: {type(e).__name__}: {e}');result={'ru_id':f'RU-{i:03d}','passed':False,'detail':'Unattributed evaluator error'}
  results.append(result)
 print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}));return 2 if infra else 0
if __name__=='__main__':raise SystemExit(main())
