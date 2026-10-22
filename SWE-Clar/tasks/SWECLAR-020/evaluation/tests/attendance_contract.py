"""Private behavioral oracle for six frozen attendance requirement units."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import traceback
import time
from urllib.parse import quote
sys.path.insert(0,'/public_tests')
from attendance_support import Application,ReaderService,browser_session,request,CandidateFailure
from test_public import run as public_run,login as page_login
from playwright.sync_api import expect,TimeoutError as BrowserTimeout, Error as BrowserError


class Checks:
    def __init__(self):self.passed=0
    def require(self,condition,message):
        if not condition:raise CandidateFailure(message)
        self.passed+=1


def api(c,app,path,body=None,token=None,method=None,status=200,code=None):
    result=request(app,path,body,token,method)
    c.require(result['status']==status,f'{path}: expected {status}, got {result["status"]}: {result["body"]}')
    if code is not None:
        c.require(result['body'].get('error',{}).get('code')==code,f'{path}: expected error code {code}, got {result["body"]}')
    return result['body']


def tokens(c,app):
    return {u['id']:api(c,app,'/api/login',{'username':u['username'],'password':u['password']})['token'] for u in app.seed['users'] if u['active']}


def reading(c,reader,uid='tag-a',at=100,interaction='tap',device='desk-a'):
    return api(c,reader,'/readings',{'uid':uid,'device_id':device,'interaction':interaction,'at':at},status=201)['reading']


def scan(c,app,reader,token,uid='tag-a',at=100,direction='in'):
    r=reading(c,reader,uid,at)
    value=api(c,app,'/api/scans',{'reading_id':r['id'],'direction':direction},token,status=201)
    return value['scan']


def confirm(c,app,token,s,recipient=None,status=201,code=None):
    return api(c,app,'/api/scans/'+quote(s['id'],safe='')+'/confirm',{'recipient_id':recipient},token,status=status,code=code)


def projected(value,keys):return {k:value[k] for k in keys}


def gate_one(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app)
        expected={'teacher-a':['student-a'],'teacher-b':['student-a','student-b'],'teacher-c':['student-c'],'admin-a':['student-a','student-b','student-c'],'parent-a':['student-a'],'parent-b':['student-a','student-b'],'parent-c':['student-c']}
        for uid,ids in expected.items():
            roster=api(c,app,'/api/roster',token=t[uid]);c.require([s['id'] for s in roster['students']]==ids,'Scoped roster fixture order')
            c.require(all(s['presence']=='out' for s in roster['students']),'Initial actual presence')
            if uid.startswith('parent'):
                c.require(roster['guardians']==roster['tags']==roster['devices']==[],'Parents do not receive operational identity mappings')
            else:
                c.require(all(set(g['student_ids'])<=set(ids) for g in roster['guardians']),'Guardian links clipped to scope')
            user=api(c,app,'/api/me',token=t[uid])['user'];c.require('password' not in user and 'digest' not in user and 'token' not in user,'Ordinary user excludes credentials')
        api(c,app,'/api/login',{'username':'parent_off','password':'synthetic-parent-off'},status=401)
        api(c,app,'/api/login',{'username':'student-a','password':'anything'},status=401)
        api(c,app,'/api/roster',status=401)
        api(c,app,'/api/tags/tag-a',{'active':False},t['teacher-a'],'PATCH',403)
        api(c,app,'/api/guardians/unknown',{'active':False},t['parent-a'],'PATCH',403)
        api(c,app,'/api/tags/tag-a',{'active':False,'student_id':'student-c'},t['admin-a'],'PATCH')
        api(c,app,'/api/guardians/guardian-a',{'active':False,'student_ids':['student-c']},t['admin-a'],'PATCH')
        app.stop();app.start();api(c,app,'/api/me',token=t['admin-a'],status=401);t=tokens(c,app)
        roster=api(c,app,'/api/roster',token=t['admin-a']);tag=next(x for x in roster['tags'] if x['uid']=='tag-a');guardian=next(x for x in roster['guardians'] if x['id']=='guardian-a')
        c.require(not tag['active'] and tag['student_id']=='student-a','Durable flag update ignores reassignment')
        c.require(not guardian['active'] and guardian['student_ids']==['student-a'],'Guardian flags durable, protected membership')
        api(c,app,'/api/logout',{},t['parent-a']);api(c,app,'/api/me',token=t['parent-a'],status=401)
        api(c,app,'/api/me',token=t['parent-b'])
    public_run();c.require(True,'Real browser visible baseline')


def gate_two(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app)
        for uid,device,interaction,status in [('tag-a','desk-a','proximity',422),('unknown','desk-a','tap',422),('tag-revoked','desk-a','tap',422),('tag-a','desk-off','tap',422),('tag-c','desk-a','tap',404)]:
            r=reading(c,reader,uid,100,interaction,device)
            api(c,app,'/api/scans',{'reading_id':r['id'],'direction':'in'},t['teacher-a'],status=status)
        r=reading(c,reader,at=123)
        api(c,app,'/api/scans',{'reading_id':r['id'],'direction':'in'},t['parent-a'],status=403)
        api(c,app,'/api/scans',{'reading_id':'missing','direction':'in'},t['teacher-a'],status=404)
        payload={'reading_id':r['id'],'direction':'in','uid':'tag-c','at':0,'interaction':'proximity'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:request(app,'/api/scans',payload,t['teacher-a']),range(4)))
        c.require(sorted(x['status'] for x in results)==[200,200,200,201],'Concurrent reading has one pending creation')
        s=results[0]['body']['scan'];c.require(all(x['body']['scan']['id']==s['id'] for x in results),'Reading replay identity stable')
        c.require(projected(s,['reading_id','student_id','tag_uid','device_id','direction','at','state','created_by','attendance_id'])=={'reading_id':r['id'],'student_id':'student-a','tag_uid':'tag-a','device_id':'desk-a','direction':'in','at':123,'state':'pending','created_by':'teacher-a','attendance_id':None},'Stored metadata comes from actual reader, not forged fields')
        c.require(['GET','/readings/'+quote(r['id'],safe='')] in reader.requests(),'Candidate actually requested immutable reader record')
        api(c,app,'/api/scans',{'reading_id':r['id'],'direction':'out'},t['teacher-a'],status=409)
        api(c,app,'/api/scans',payload,t['teacher-c'],status=404)
        c.require(api(c,app,'/api/attendance',token=t['admin-a'])['attendance']==[],'Scanning is not confirmation')
        c.require(api(c,app,'/api/inbox',token=t['parent-a'])['entries']==[],'Pending scan does not deliver notification')
        app.stop();app.start();t=tokens(c,app)
        c.require(api(c,app,'/api/scans',payload,t['teacher-b'])['scan']['id']==s['id'],'Reading mapping survives restart and retains original creator')
        reader.process.terminate();reader.process.wait(timeout=5);reader.process=None
        api(c,app,'/api/scans',{'reading_id':'connection-probe','direction':'in'},t['teacher-a'],status=502)


def gate_three(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app);s=scan(c,app,reader,t['teacher-a'])
        confirm(c,app,t['parent-a'],s,status=403,code='forbidden');confirm(c,app,t['teacher-c'],s,status=404,code='not_found')
        api(c,app,'/api/tags/tag-a',{'active':False},t['admin-a'],'PATCH')
        confirm(c,app,t['teacher-a'],s,status=422,code='inactive_tag')
        c.require(api(c,app,'/api/attendance',token=t['admin-a'])['attendance']==[],'Revocation cannot produce attendance')
        c.require(api(c,app,'/api/scans',token=t['teacher-a'])['scans'][0]['state']=='pending','Rejected authorization remains pending')
        api(c,app,'/api/tags/tag-a',{'active':True},t['admin-a'],'PATCH')
        result=api(c,app,'/api/scans/'+quote(s['id'],safe='')+'/confirm',{'confirmed_by':'teacher-c','student_id':'student-c','at':0,'direction':'out'},t['teacher-b'],status=201)['attendance']
        c.require(projected(result,['confirmed_by','student_id','at','direction'])=={'confirmed_by':'teacher-b','student_id':'student-a','at':100,'direction':'in'},'Authentication and stored scan determine immutable completion')
        api(c,app,'/api/tags/tag-a',{'active':False},t['admin-a'],'PATCH')
        c.require(confirm(c,app,t['teacher-a'],s,status=200)['attendance']['id']==result['id'],'Authorized completed replay not undone by tag revocation')


def gate_four(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app);entry=scan(c,app,reader,t['teacher-a'])
        confirm(c,app,t['teacher-a'],entry,'guardian-a',400,'invalid_request');confirm(c,app,t['teacher-a'],entry)
        s=scan(c,app,reader,t['teacher-a'],direction='out',at=101)
        for recipient,status,code in [(None,422,'recipient_required'),('',400,'invalid_request'),(True,400,'invalid_request'),('guardian-c',422,'unauthorized_recipient'),('guardian-off',422,'unauthorized_recipient'),('unknown',422,'unauthorized_recipient')]:confirm(c,app,t['teacher-a'],s,recipient,status,code)
        api(c,app,'/api/tags/tag-a',{'active':False},t['admin-a'],'PATCH')
        confirm(c,app,t['teacher-a'],s,None,422,'inactive_tag')
        api(c,app,'/api/tags/tag-a',{'active':True},t['admin-a'],'PATCH')
        old=scan(c,app,reader,t['teacher-a'],direction='out',at=99)
        confirm(c,app,t['teacher-a'],old,None,422,'recipient_required')
        confirm(c,app,t['teacher-a'],old,'guardian-c',422,'unauthorized_recipient')
        confirm(c,app,t['teacher-a'],old,'guardian-a',409,'stale_reading')
        api(c,app,'/api/guardians/guardian-a',{'active':False},t['admin-a'],'PATCH');confirm(c,app,t['teacher-a'],s,'guardian-a',422,'unauthorized_recipient')
        c.require(next(x for x in api(c,app,'/api/roster',token=t['teacher-a'])['students'] if x['id']=='student-a')['presence']=='in','Rejected recipient preserves presence')
        c.require(len(api(c,app,'/api/attendance',token=t['teacher-a'])['attendance'])==1,'No rejected handoff recorded')
        api(c,app,'/api/guardians/guardian-a',{'active':True},t['admin-a'],'PATCH')
        record=confirm(c,app,t['teacher-a'],s,'guardian-a')['attendance'];c.require(record['recipient_id']=='guardian-a','Correct guardian persisted')
        api(c,app,'/api/guardians/guardian-a',{'active':False},t['admin-a'],'PATCH')
        c.require(confirm(c,app,t['teacher-b'],s,'guardian-a',200)['attendance']['id']==record['id'],'Replay after guardian revocation preserves result')
        confirm(c,app,t['teacher-a'],s,'guardian-c',409,'confirmation_conflict')
        confirm(c,app,t['teacher-a'],s,None,422,'recipient_required')


def gate_five(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app);s=scan(c,app,reader,t['teacher-a'],at=200)
        path='/api/scans/'+quote(s['id'],safe='')+'/confirm'
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:request(app,path,{},t['teacher-a']),range(4)))
        c.require(sorted(x['status'] for x in results)==[200,200,200,201],'One committed completion across concurrent retries')
        rid=results[0]['body']['attendance']['id'];c.require(all(x['body']['attendance']['id']==rid for x in results),'Replay preserves identity')
        bad=scan(c,app,reader,t['teacher-a'],at=201);confirm(c,app,t['teacher-a'],bad,status=409,code='attendance_conflict')
        old_in=scan(c,app,reader,t['teacher-a'],at=199);confirm(c,app,t['teacher-a'],old_in,status=409,code='stale_reading')
        stale=scan(c,app,reader,t['teacher-a'],direction='out',at=199);confirm(c,app,t['teacher-a'],stale,'guardian-a',409,'stale_reading')
        out=scan(c,app,reader,t['teacher-a'],direction='out',at=200);confirm(c,app,t['teacher-a'],out,'guardian-a')
        left=scan(c,app,reader,t['teacher-a'],at=201);right=scan(c,app,reader,t['teacher-a'],at=201)
        with ThreadPoolExecutor(max_workers=2) as pool:competing=list(pool.map(lambda row:request(app,'/api/scans/'+quote(row['id'],safe='')+'/confirm',{},t['teacher-a']),[left,right]))
        c.require(sorted(x['status'] for x in competing)==[201,409],'Competing scans cannot both transition same student')
        c.require(next(x for x in competing if x['status']==409)['body'].get('error',{}).get('code')=='attendance_conflict','Concurrent rejected transition has its documented error code')
        other=scan(c,app,reader,t['teacher-b'],uid='tag-b',at=1);confirm(c,app,t['teacher-b'],other)
        records=api(c,app,'/api/attendance',token=t['admin-a'])['attendance'];c.require(len(records)==4,'Only valid completed events persisted')
        c.require(len(api(c,app,'/api/inbox',token=t['parent-a'])['entries'])==3,'Atomic replay never duplicates inbox delivery')
        app.stop();app.start();t=tokens(c,app)
        c.require(confirm(c,app,t['teacher-b'],s,status=200)['attendance']['id']==rid,'Older completed event replays after later transitions and restart')
        c.require(len(api(c,app,'/api/attendance',token=t['admin-a'])['attendance'])==4,'Replay does not append attendance')


def delayed_account_checks(c,app):
    with browser_session() as browser:
        page=browser.new_page();page.goto(app.url)
        page.evaluate('window.probe = new AttendanceClient()')
        users={u['id']:u for u in app.seed['users']}
        def login(uid):page.evaluate('(u)=>probe.login(u.username,u.password)',users[uid])
        login('parent-a')
        for response_status in [200,401]:
            held=[];page.evaluate('window.benchmarkHeld=0')
            def hold(route):
                if held:route.continue_();return
                response=route.fetch();held.append((route,response));page.evaluate('window.benchmarkHeld=1')
            page.route('**/api/inbox',hold)
            page.evaluate('()=>{window.oldRefresh=Promise.resolve(probe.refresh()).catch(()=>null);}')
            page.wait_for_function('window.benchmarkHeld===1')
            login('parent-c')
            route,response=held[0]
            try:
                if response_status==200:route.fulfill(response=response)
                else:route.fulfill(status=401,content_type='application/json',body='{"error":{"code":"unauthenticated"}}')
            except BrowserError:
                if route.request.failure is None:raise
            page.evaluate('()=>oldRefresh');page.unroute('**/api/inbox',hold)
            c.require(page.evaluate('probe.user.id')=='parent-c','Old account response cannot overwrite or clear current account')
            c.require(page.evaluate('probe.inbox.length')==0,'Old parent inbox cannot reappear after account switch')
            login('parent-a')
        def unauthorized(route):route.fulfill(status=401,content_type='application/json',body='{"error":{"code":"unauthenticated"}}')
        page.route('**/api/me',unauthorized);page.evaluate('()=>Promise.resolve(probe.refresh()).catch(()=>null)')
        c.require(page.evaluate('probe.user===null && probe.inbox.length===0 && probe.students.length===0'),'Current unauthorized response clears private data')
        page.unroute('**/api/me',unauthorized);page.evaluate('probe.dispose()')


def gate_six(c):
    with ReaderService() as reader,Application(reader_url=reader.url) as app:
        t=tokens(c,app);s=scan(c,app,reader,t['teacher-a']);record=confirm(c,app,t['teacher-a'],s)['attendance']
        a=api(c,app,'/api/inbox',token=t['parent-a'])['entries'];b=api(c,app,'/api/inbox',token=t['parent-b'])['entries']
        c.require(len(a)==len(b)==1 and a[0]['id']!=b[0]['id'],'Separate durable inbox per linked parent')
        for entry in [a[0],b[0]]:
            c.require(projected(entry,['attendance_id','student_id','direction','at','confirmed_by','recipient_id','read'])=={'attendance_id':record['id'],'student_id':'student-a','direction':'in','at':100,'confirmed_by':'teacher-a','recipient_id':None,'read':False},'Inbox content derives from committed attendance')
        c.require(api(c,app,'/api/inbox',token=t['parent-c'])['entries']==[],'Unrelated parent receives no entry')
        delayed_account_checks(c,app)
        api(c,app,'/api/inbox',token=t['admin-a'],status=403)
        path='/api/inbox/'+quote(a[0]['id'],safe='')
        api(c,app,path,{'read':True},t['parent-b'],'PUT',404)
        for value in [True,True,False,True]:api(c,app,path,{'read':value,'student_id':'student-c'},t['parent-a'],'PUT')
        c.require(not api(c,app,'/api/inbox',token=t['parent-b'])['entries'][0]['read'],'Read state cannot leak between owners')
        app.stop();app.start();t=tokens(c,app);c.require(api(c,app,'/api/inbox',token=t['parent-a'])['entries'][0]['read'],'Read state survives restart')
        with browser_session() as browser:
            page=browser.new_page();page_login(page,app,next(u for u in app.seed['users'] if u['id']=='teacher-a'))
            pending=scan(c,app,reader,t['teacher-a'],direction='out',at=101)
            page.reload();page_login(page,app,next(u for u in app.seed['users'] if u['id']=='teacher-a'));expect(page.locator('[data-scan-id]')).to_have_count(1)
            lost=[]
            def lose(route):
                if lost:route.continue_();return
                lost.append(route.fetch());route.abort()
            page.route('**/api/scans/*/confirm',lose)
            page.locator('[data-recipient]').select_option('guardian-a');page.locator('[data-confirm]').click()
            # Refresh recovery or same-scan retry are both valid strategies.
            deadline=time.monotonic()+10
            while not lost and time.monotonic()<deadline:page.wait_for_timeout(50)
            c.require(bool(lost),'Confirmation response committed then intentionally lost')
            page.reload();page_login(page,app,next(u for u in app.seed['users'] if u['id']=='teacher-a'));expect(page.locator('[data-attendance-id]')).to_have_count(2);expect(page.locator('[data-scan-id]')).to_have_count(0)
            c.require(len(api(c,app,'/api/scans',token=t['teacher-a'])['scans'])==2,'Lost confirmation must not synthesize a replacement reading')
            page.locator('#logout').click();page_login(page,app,next(u for u in app.seed['users'] if u['id']=='parent-a'))
            expect(page.locator('[data-entry-id]')).to_have_count(2)
            with page.expect_response(lambda response: response.request.method=='PUT' and '/api/inbox/' in response.url) as saved:
                page.locator('[data-read]').last.check()
            c.require(saved.value.status==200,'Read update acknowledged before reload')
            page.reload();page_login(page,app,next(u for u in app.seed['users'] if u['id']=='parent-a'));expect(page.locator('[data-read]').last).to_be_checked()
            page.locator('#logout').click();expect(page.locator('#workspace')).to_be_hidden()
            storage=page.evaluate('JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])')
            c.require(all(u['password'] not in storage for u in app.seed['users']),'Fixture passwords absent from browser persistence')


GATES=[gate_one,gate_two,gate_three,gate_four,gate_five,gate_six]

def main():
    results=[];errors=[]
    for index,gate in enumerate(GATES,1):
        checks=Checks();row={'ru_id':f'RU-{index:03d}','passed':False}
        try:gate(checks);row.update(passed=True,detail='All executable checks passed')
        except (AssertionError,KeyError,TypeError,IndexError,ValueError,StopIteration,BrowserTimeout) as error:row['detail']=type(error).__name__+': '+str(error)
        except Exception as error:row['detail']='Unattributed evaluator/environment error: '+repr(error);errors.append({'ru_id':row['ru_id'],'traceback':traceback.format_exc()})
        row['checks_passed']=checks.passed;results.append(row)
    print(json.dumps({'harness_ok':not errors,'results':results,'infrastructure_errors':errors}));return 0 if not errors else 2

if __name__=='__main__':raise SystemExit(main())
