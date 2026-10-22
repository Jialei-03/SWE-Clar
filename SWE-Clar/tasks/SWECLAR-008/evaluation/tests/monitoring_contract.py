"""Independent HTTP, persistence and real-browser observations for six frozen RUs.

Fixtures and expected boundary tables are evaluator inputs. No candidate module is
imported by this process; candidate execution stays in the public App transport.
"""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures,copy,csv,io,json,os,re,sys,traceback
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs
sys.path.insert(0,'/public_tests')
from public_support import application,request,database_rows,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
M=60000;D=86400000;BASE=1704067200000  # UTC midnight, independently selected synthetic clock
FIELDS=['household_id','room_id','event_count','sleep_event_count','alert_count']


def fixture():
    return {'clock_ms':BASE+12*60*M,'feed_token':'evaluation-feed-secret',
        'households':[{'id':h,'name':name,'freshness_minutes':10,'night_start':1320,'night_end':360,'sleep_start':1380,'sleep_end':420} for h,name in [('alpha','Alpha <zone>'),('beta','Beta isolated'),('closed','Unassigned secret')]],
        'users':[{'id':u,'name':name,'role':role,'household_id':home,'assignments':assign,'password':'evaluation-password'} for u,name,role,home,assign in [('resident','Local reader','individual','alpha',[]),('other','Other reader','individual','beta',[]),('helper','Assigned helper','caregiver',None,['alpha','beta']),('limited','Limited helper','caregiver',None,['alpha']),('empty','Unassigned helper','caregiver',None,[])]],
        'rooms':[{'household_id':h,'id':r,'name':h+' '+r+' <b>literal</b>'} for h in ['alpha','beta','closed'] for r in ['zone','empty']],
        'sensors':[{'household_id':h,'id':s,'room_id':'zone','name':h+' '+s+' <img src=x onerror=alert(1)>','kind':kind} for h in ['alpha','beta','closed'] for s,kind in [('contact','contact'),('presence','presence')]],'events':[],'rules':[]}


def event(ident,t,value,sensor='contact',home='alpha'):
    return {'household_id':home,'event_id':ident,'sensor_id':sensor,'timestamp_ms':t,'value':value}


def rule(kind='fridge_open',threshold=1,sensor='contact',home='alpha',room='zone',enabled=True,severity='warning'):
    return {'household_id':home,'room_id':room,'kind':kind,'sensor_id':sensor,'enabled':enabled,'threshold_minutes':threshold,'severity':severity}


def login(app,user='resident'):
    return request(app,'/api/login',body={'id':user,'password':'evaluation-password'},method='POST')['token']


def get(app,endpoint,token,t=None,home='alpha',**kwargs):
    params={'household_id':home,**kwargs}
    if t is not None:params['as_of']=t
    return request(app,'/api/'+endpoint+'?'+urlencode(params),token)


def ingest(app,f,row,status=200):return request(app,'/api/ingest',f['feed_token'],row,'POST',status=status)

def saved(app,token,home='alpha',room='zone'):return get(app,'rules',token,home=home,room_id=room)['rules']

def projection(rows,keys):return [{k:row[k] for k in keys} for row in rows]

def observed(app,token,t,home='alpha'):
    data=get(app,'snapshot',token,t,home);assert data['as_of']==t
    return {(r['room_id'],s['sensor_id']):(s['value'],s['timestamp_ms'],s['stale']) for r in data['rooms'] for s in r['sensors']}


def ui_login(page,app,user='helper'):
    page.goto(app.url);page.locator('#account').fill(user);page.locator('#password').fill('evaluation-password');page.locator('#login-form button').click()
    expect(page.locator('#application')).to_be_visible();expect(page.locator('[data-room-id]')).to_have_count(2)


class HeldResponse:
    """Hold one real server response to deterministically reorder browser delivery."""
    def __init__(self,page,pattern):
        if '?household_id=' in pattern:
            path,home=pattern.removeprefix('**').split('?household_id=')
            home=home.removesuffix('&*')
            pattern=lambda url: household_url(url,path,home)
        self.page=page;self.pattern=pattern;self.pending=None;self.used=False
        page.route(pattern,self.capture)
    def capture(self,route):
        if self.used:route.continue_();return
        self.used=True;self.pending=(route,route.fetch())
    def wait(self):
        import time
        deadline=time.monotonic()+5
        while self.pending is None and time.monotonic()<deadline:self.page.wait_for_timeout(20)
        assert self.pending is not None,'Expected actual request was not made'
    def release(self):
        route,response=self.pending;route.fulfill(response=response)
        self.page.wait_for_timeout(150)
        self.page.unroute(self.pattern,self.capture)


def household_url(url,path,home):
    parts=urlsplit(url)
    return parts.path==path and parse_qs(parts.query).get('household_id')==[home]


def sign_in_existing(page,user):
    page.locator('#account').fill(user);page.locator('#password').fill('evaluation-password');page.locator('#login-form button').click()
    expect(page.locator('#application')).to_be_visible()


def browser_account_race(app):
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();ui_login(page,app,'resident')
            held=HeldResponse(page,'**/api/snapshot?household_id=alpha&*');paired=HeldResponse(page,'**/api/alerts?household_id=alpha&*');page.locator('#refresh').click();held.wait();paired.wait()
            page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden();assert page.locator('#rooms').inner_text()==''
            sign_in_existing(page,'other');expect(page.locator('#rooms')).to_contain_text('beta zone')
            page.evaluate("()=>{window.oldAccountFlashes=[];window.roomObserver=new MutationObserver(()=>{if(document.getElementById('rooms').textContent.includes('alpha zone'))oldAccountFlashes.push(document.getElementById('rooms').textContent);});roomObserver.observe(document.getElementById('rooms'),{subtree:true,childList:true,characterData:true});}")
            held.release();paired.release();expect(page.locator('#rooms')).to_contain_text('beta zone');expect(page.locator('#rooms')).not_to_contain_text('alpha zone')
            assert page.evaluate('oldAccountFlashes')==[],'A late successful response exposed old household content'
            page.evaluate('roomObserver.disconnect()')
        finally:browser.close()


def browser_selection_and_retry(app):
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();ui_login(page,app)
            held=HeldResponse(page,'**/api/snapshot?household_id=alpha&*');paired=HeldResponse(page,'**/api/alerts?household_id=alpha&*');page.locator('#refresh').click();held.wait();paired.wait()
            page.locator('#household').select_option('beta');expect(page.locator('#rooms')).to_contain_text('beta zone')
            page.evaluate("()=>{window.oldAccountFlashes=[];window.roomObserver=new MutationObserver(()=>{if(document.getElementById('rooms').textContent.includes('alpha zone'))oldAccountFlashes.push(document.getElementById('rooms').textContent);});roomObserver.observe(document.getElementById('rooms'),{subtree:true,childList:true,characterData:true});}")
            held.release();paired.release();expect(page.locator('#rooms')).to_contain_text('beta zone');expect(page.locator('#rooms')).not_to_contain_text('alpha zone')
            assert page.evaluate('oldAccountFlashes')==[],'A late successful response exposed old household content'
            page.evaluate('roomObserver.disconnect()')
            expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('off',re.I))
            held=HeldResponse(page,'**/api/snapshot?household_id=beta&*');paired=HeldResponse(page,'**/api/alerts?household_id=beta&*');page.locator('#refresh').click();held.wait();paired.wait()
            page.locator('#as-of').fill('2024-01-01T11:59:00.000Z');page.locator('#as-of').dispatch_event('change')
            expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('unknown',re.I))
            page.evaluate("()=>{window.oldTimeFlashes=[];window.timeObserver=new MutationObserver(()=>{const state=document.querySelector('[data-sensor-id=contact] .state');if(state&&state.textContent.toLowerCase()==='off')oldTimeFlashes.push(state.textContent);});timeObserver.observe(document.getElementById('rooms'),{subtree:true,childList:true,characterData:true});}")
            held.release();paired.release();expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('unknown',re.I))
            assert page.evaluate('oldTimeFlashes')==[],'Old evaluation-time state was briefly rendered'
            page.evaluate('timeObserver.disconnect()')
            def fail(route):route.fulfill(status=503,content_type='application/json',body='{"error":{"code":"temporary_storage_failure"}}')
            page.route('**/api/snapshot?*',fail);page.locator('#refresh').click()
            expect(page.locator('#status')).to_contain_text(re.compile('fail|error|unable|unavailable',re.I))
            page.unroute('**/api/snapshot?*',fail)
            page.locator('#as-of').fill('2024-01-01T12:00:00.000Z');page.locator('#as-of').dispatch_event('change');page.locator('#refresh').click()
            expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('off',re.I))
        finally:browser.close()


def check_1():
    f=fixture()
    with application(f) as app:
        for body in [{'id':'resident','password':'wrong'},{'id':'missing','password':'evaluation-password'}]:request(app,'/api/login',body=body,method='POST',status=401)
        token=login(app);second=login(app);other=login(app,'other');assert token and token!=second and token!=other
        for bad in [None,'forged',f['feed_token']]:request(app,'/api/me',bad,status=401)
        row=event('replay',BASE,True)
        for bad in [None,'wrong-feed',token]:request(app,'/api/ingest',bad,row,'POST',status=401)
        malformed=[{**row,'timestamp_ms':x} for x in [True,-1,1.5,'10',253402300800000,10**100,None]]
        malformed += [{**row,'value':x} for x in [0,1,'true',None,{}]]
        malformed += [{**row,'event_id':x} for x in ['', 'bad space','x'*65,2]]
        malformed += [{k:v for k,v in row.items() if k!='sensor_id'},{**row,'role':'caregiver'}]
        for bad in malformed:ingest(app,f,bad,400)
        assert database_rows(app,'events')==[]
        for bad in [{**row,'sensor_id':'missing'},{**row,'household_id':'missing'}]:ingest(app,f,bad,404)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(lambda _:ingest(app,f,row),range(8)))
        assert all(r['accepted'] is True for r in responses)
        assert sum(r['duplicate'] is False for r in responses)==1 and sum(r['duplicate'] is True for r in responses)==7
        for key,value in [('sensor_id','presence'),('timestamp_ms',BASE+1),('value',False)]:ingest(app,f,{**row,key:value},409)
        ingest(app,f,{**row,'household_id':'beta'})
        for e in [event('old',0,False),event('future',253402300799999,False)]:ingest(app,f,e)
        stored=projection(database_rows(app,'events'),row.keys());assert len(stored)==4
        assert next(r for r in stored if r['household_id']=='alpha' and r['event_id']=='replay')==row
        for endpoint in ['/api/me','/api/homes',f'/api/snapshot?household_id=alpha&as_of={BASE}']:
            raw=json.dumps(request(app,endpoint,token));assert all(secret not in raw for secret in ['evaluation-password',f['feed_token'],other,second,'password_hash'])
        request(app,'/api/logout',token,{},'POST');request(app,'/api/me',token,status=401);request(app,'/api/me',second)
        app.stop();app.start();assert projection(database_rows(app,'events'),row.keys())==stored
        assert observed(app,second,0)['zone','contact']==(False,0,False)
        assert observed(app,second,253402300799999)['zone','contact']==(False,253402300799999,False)


def check_2():
    f=fixture();f['events']=[event('same',BASE,True),event('same',BASE,False,home='beta')]
    f['rules']=[rule(home='alpha',threshold=3),rule(home='beta',threshold=8)]
    with application(f) as app:
        tokens={u:login(app,u) for u in ['resident','other','helper','limited','empty']}
        expected={'resident':['alpha'],'other':['beta'],'helper':['alpha','beta'],'limited':['alpha'],'empty':[]}
        endpoints=[('snapshot',{'as_of':BASE}),('alerts',{'as_of':BASE}),('report',{'as_of':BASE}),('report.csv',{'as_of':BASE}),('rules',{'room_id':'zone'})]
        for user,token in tokens.items():
            assert [h['id'] for h in request(app,'/api/homes',token)['households']]==expected[user]
            assert request(app,'/api/me',token)['user']['id']==user
            for home in ['alpha','beta','closed','absent']:
                for ep,extra in endpoints:
                    url='/api/'+ep+'?'+urlencode({'household_id':home,**extra})
                    if home not in expected[user]:
                        raw=request(app,url,token,status=403,raw=True);assert all(n not in raw for n in ['Unassigned secret','isolated','literal','onerror'])
                    else:request(app,url,token,raw=ep.endswith('.csv'))
        for ep,extra in endpoints:request(app,'/api/'+ep+'?'+urlencode({'household_id':'alpha',**extra}),'forged',status=401)
        for ep in ['snapshot','alerts','report','report.csv']:
            request(app,'/api/'+ep+'?'+urlencode({'household_id':'beta','as_of':BASE,'user':'helper','role':'caregiver'}),tokens['resident'],status=403)
        assert observed(app,tokens['helper'],BASE,'alpha')['zone','contact']==(True,BASE,False)
        assert observed(app,tokens['helper'],BASE,'beta')['zone','contact']==(False,BASE,False)
        assert saved(app,tokens['helper'],'alpha')[0]['threshold_minutes']==3
        assert saved(app,tokens['helper'],'beta')[0]['threshold_minutes']==8
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();ui_login(page,app,'resident')
                expect(page.locator('#rooms')).to_contain_text('alpha zone')
                page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden();assert page.locator('#rooms').inner_text()==''
                ui_login(page,app,'other');expect(page.locator('#rooms')).to_contain_text('beta zone');expect(page.locator('#rooms')).not_to_contain_text('alpha zone')
            finally:browser.close()

        browser_account_race(app)


def check_3():
    f=fixture();t=f['clock_ms'];f['events']=[event('z',t-M,True),event('a',t-M,False),event('future',t+1,False),event('older',t-9*M,False),event('same-id',t,False,home='beta')]
    with application(f) as app:
        token=login(app,'helper');before=database_rows(app,'events')
        for time,value,stamp,stale in [(t-10*M,None,None,True),(t-M,True,t-M,False),(t,True,t-M,False),(t+9*M,False,t+1,False),(t+10*M+2,False,t+1,True)]:
            assert observed(app,token,time)['zone','contact']==(value,stamp,stale)
        # Exact freshness boundary, independent of the earlier future observation.
        ingest(app,f,event('presence',t,False,'presence'))
        assert observed(app,token,t+10*M)['zone','presence']==(False,t,False)
        assert observed(app,token,t+10*M+1)['zone','presence']==(False,t,True)
        rows=get(app,'snapshot',token,t)['rooms'];assert [r['room_id'] for r in rows]==['empty','zone']
        assert [s['sensor_id'] for s in rows[1]['sensors']]==['contact','presence']
        assert rows[0]['sensors']==[];assert rows[1]['name']=='alpha zone <b>literal</b>'
        assert len(database_rows(app,'events'))==len(before)+1
        for bad in ['-1','true','1.5','253402300800000']:
            request(app,'/api/snapshot?household_id=alpha&as_of='+bad,token,status=400)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));ui_login(page,app)
                expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('on',re.I))
                expect(page.locator('#rooms')).to_contain_text('<b>literal</b>');assert page.locator('#rooms img,#rooms b').count()==0
                ingest(app,f,event('live',t,False));expect(page.locator('[data-sensor-id="contact"] .state')).to_have_text(re.compile('off',re.I),timeout=5000)
                for width,height in [(390,844),(1280,900)]:
                    page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.locator('#refresh').scroll_into_view_if_needed();expect(page.locator('#refresh')).to_be_enabled()
                assert not errors,errors
            finally:browser.close()

        browser_selection_and_retry(app)


def check_4():
    f=fixture();initial=rule(threshold=4);f['rules']=[initial,rule('no_occupancy',2,'presence'),rule(home='beta',threshold=9)]
    with application(f) as app:
        helper=login(app,'helper');reader=login(app);limited=login(app,'limited')
        before=database_rows(app,'rules')
        request(app,'/api/rules',reader,{**initial,'threshold_minutes':1},'PUT',status=403)
        request(app,'/api/rules',limited,rule(home='beta'),'PUT',status=403)
        assert database_rows(app,'rules')==before
        invalid=[{**initial,'threshold_minutes':v} for v in [True,False,-0.1,1440.1,'1',None,[],10**1000]]
        invalid += [{**initial,'enabled':v} for v in [0,1,'true',None]]
        invalid += [{**initial,'kind':v} for v in ['unknown','FRIDGE_OPEN',None,[]]]
        invalid += [{**initial,'severity':v} for v in ['urgent',None,0,[]]]
        invalid += [{**initial,'sensor_id':'presence'},{**initial,'sensor_id':'missing'},{**initial,'room_id':'empty'},{**initial,'room_id':'missing'}]
        for row in invalid:request(app,'/api/rules',helper,row,'PUT',status=400);assert database_rows(app,'rules')==before
        for kind,sensor in [('fridge_open','contact'),('exterior_open_night','contact'),('bathroom_occupied_day','presence'),('bathroom_occupied_night','presence'),('no_occupancy','presence')]:
            for n in [0,0.25,1440]:
                row=rule(kind,n,sensor,severity='critical');result=request(app,'/api/rules',helper,row,'PUT')['rule'];assert projection([result],row.keys())==[row]
                actual=next(r for r in saved(app,helper) if r['kind']==kind);assert projection([actual],row.keys())==[row] and type(actual['enabled']) is bool
        disabled=rule(enabled=False,threshold=0,severity='info');request(app,'/api/rules',helper,disabled,'PUT')
        assert [r['kind'] for r in saved(app,helper)]==sorted(r['kind'] for r in saved(app,helper))
        assert saved(app,helper,'beta')[0]['threshold_minutes']==9
        rows=database_rows(app,'rules');app.stop();app.start();assert database_rows(app,'rules')==rows
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();ui_login(page,app,'resident');assert page.locator('#save-rule').is_hidden() or page.locator('#save-rule').is_disabled()
                page.locator('#logout').click();ui_login(page,app,'helper');page.locator('#rule-room').select_option('zone');page.locator('#rule-kind').select_option('fridge_open')
                expect(page.locator('#rule-threshold')).to_have_value('0');page.locator('#rule-sensor').select_option('contact');page.locator('#rule-threshold').fill('0.5');page.locator('#rule-enabled').check();page.locator('#save-rule').click()
                expect(page.locator('#saved-rules')).to_contain_text('0.5');assert next(r for r in saved(app,helper) if r['kind']=='fridge_open')['threshold_minutes']==0.5
                page.locator('#rule-threshold').fill('-1');page.locator('#save-rule').click()
                expect(page.locator('#rule-status')).to_contain_text(re.compile('fail|error|invalid|reject',re.I));expect(page.locator('#rule-sensor')).to_have_value('contact')
                assert next(r for r in saved(app,helper) if r['kind']=='fridge_open')['sensor_id']=='contact'
                page.locator('#rule-threshold').fill('2');page.locator('#save-rule').click();expect(page.locator('#rule-threshold')).to_have_value('2');expect(page.locator('#saved-rules')).to_contain_text(re.compile(r'(?<![0-9])2(?![0-9])'))
            finally:browser.close()


def alert_case(kind,states,queries,threshold=1,night=(1320,360),freshness=10000,enabled=True):
    """queries contains explicit (time, expected [(onset, trigger)]) table, not a copied oracle."""
    f=fixture();h=f['households'][0];h.update(night_start=night[0],night_end=night[1],freshness_minutes=freshness)
    sensor='contact' if kind in ['fridge_open','exterior_open_night'] else 'presence'
    f['events']=[event(ident,t,v,sensor) for ident,t,v in states];f['rules']=[rule(kind,threshold,sensor,enabled=enabled,severity='critical')]
    with application(f) as app:
        token=login(app);identities={}
        for time,expected in queries:
            data=get(app,'alerts',token,time);assert data['as_of']==time
            rows=data['alerts'];assert [(r['start_ms'],r['trigger_ms']) for r in rows]==expected,(kind,time,rows,expected)
            for row in rows:
                assert {k:row[k] for k in ['household_id','room_id','kind','sensor_id','severity']}=={'household_id':'alpha','room_id':'zone','kind':kind,'sensor_id':sensor,'severity':'critical'}
                assert isinstance(row['explanation'],str) and row['explanation'].strip()
                assert isinstance(row['alert_id'],str) and row['alert_id'].strip()
                if row['start_ms'] in identities:assert identities[row['start_ms']]==row['alert_id']
                identities[row['start_ms']]=row['alert_id']
            assert [(r['alert_id'],r['start_ms'],r['trigger_ms']) for r in get(app,'alerts',token,time)['alerts']]==[(r['alert_id'],r['start_ms'],r['trigger_ms']) for r in rows]
        if len(identities)>1:assert len(set(identities.values()))==len(identities)


def check_5():
    t=BASE+12*60*M
    alert_case('fridge_open',[('first',t,True),('repeat',t+M,True),('end',t+3*M,False),('again',t+4*M,True)],[(t+M-1,[]),(t+M,[(t,t+M)]),(t+2*M,[(t,t+M)]),(t+3*M,[]),(t+5*M,[(t+4*M,t+5*M)])])
    alert_case('fridge_open',[('z',t,True),('a',t,False),('future',t+2*M,False)],[(t+M,[(t,t+M)]),(t+2*M,[])])
    alert_case('fridge_open',[('start',t,True)],[(t+10*M,[(t,t+M)]),(t+10*M+1,[])],freshness=10)
    alert_case('fridge_open',[('start',t,True)],[(t,[(t,t)]),(t+1,[(t,t)])],threshold=0)
    alert_case('fridge_open',[('start',t,True)],[(t+15000-1,[]),(t+15000,[(t,t+15000)])],threshold=0.25)
    alert_case('fridge_open',[('start',t,True)],[(t+M,[])],enabled=False)
    alert_case('no_occupancy',[('start',t,False),('same',t+M,False),('end',t+3*M,True)],[(t+M,[(t,t+M)]),(t+2*M,[(t,t+M)]),(t+3*M,[])])
    onset=BASE+21*60*M;night=BASE+22*60*M;morning=BASE+D+6*60*M
    for kind in ['bathroom_occupied_night','exterior_open_night']:
        alert_case(kind,[('start',onset,True)],[(night-1,[]),(night,[(onset,night)]),(morning-1,[(onset,night)]),(morning,[]),(night+D,[(onset,night)])],threshold=30)
    onset=BASE+5*60*M;day=BASE+6*60*M
    alert_case('bathroom_occupied_day',[('start',onset,True)],[(day-1,[]),(day,[(onset,day)]),(BASE+22*60*M,[])],threshold=30)
    for kind in ['bathroom_occupied_night','exterior_open_night']:alert_case(kind,[('start',t,True)],[(t+M,[])],night=(300,300))
    alert_case('bathroom_occupied_day',[('start',t,True)],[(t+M,[(t,t+M)])],night=(300,300))
    alert_case('bathroom_occupied_night',[('start',BASE+8*60*M,True)],[(BASE+9*60*M,[(BASE+8*60*M,BASE+9*60*M)]),(BASE+17*60*M,[])],night=(540,1020))

    # Reverse insertion order and conflicting kinds distinguish room-first sorting.
    multi=fixture();multi['clock_ms']=BASE+23*60*M
    multi['rooms']=[{'household_id':'alpha','id':room,'name':room} for room in ['z-room','a-room']]
    multi['sensors']=[];multi['rules']=[];multi['events']=[]
    expected=[]
    for room in ['z-room','a-room']:
        for sensor,kind in [('z-contact','fridge_open'),('a-contact','exterior_open_night')]:
            sid=room+'-'+sensor
            multi['sensors'].append({'household_id':'alpha','id':sid,'room_id':room,'name':sid,'kind':'contact'})
            multi['rules'].append(rule(kind,30,sid,room=room))
            onset=BASE+21*60*M
            multi['events'] += [event(sid+'-start',onset,True,sid),event(sid+'-fresh',multi['clock_ms'],True,sid)]
            expected.append((room,kind,sid,onset))
    with application(multi) as app:
        alerts=get(app,'alerts',login(app),multi['clock_ms'])['alerts']
        assert [(a['room_id'],a['kind'],a['sensor_id'],a['start_ms']) for a in alerts]==sorted(expected)

    f=fixture();f['clock_ms']=BASE+23*60*M
    f['events']=[event('contact-start',BASE+21*60*M,True),event('presence-start',BASE+21*60*M,True,'presence'),event('contact-fresh',f['clock_ms'],True),event('presence-fresh',f['clock_ms'],True,'presence')]
    f['rules']=[rule('fridge_open',30),rule('exterior_open_night',30),rule('bathroom_occupied_night',30,'presence')]
    with application(f) as app:
        token=login(app);time=f['clock_ms'];rows=get(app,'alerts',token,time)['alerts']
        assert [r['kind'] for r in rows]==['bathroom_occupied_night','exterior_open_night','fridge_open']
        assert len({r['alert_id'] for r in rows})==3
        assert get(app,'alerts',login(app,'other'),time,'beta')['alerts']==[]
        identity=[r['alert_id'] for r in rows];app.stop();app.start();assert [r['alert_id'] for r in get(app,'alerts',token,time)['alerts']]==identity
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();ui_login(page,app);expect(page.locator('[data-alert-id]')).to_have_count(3)
                for row in rows:
                    # DOM ID encoding is unrestricted: select by equality in page JS, not interpolated CSS.
                    texts=page.locator('[data-alert-id]').evaluate_all('(nodes)=>nodes.map(n=>({id:n.dataset.alertId,text:n.textContent}))')
                    assert any(r['id']==row['alert_id'] and row['explanation'] in r['text'] for r in texts)
            finally:browser.close()


def report_case(events,rules,time,expected,sleep=(1380,420),night=(1320,360),restart=False):
    f=fixture();f['events']=events;f['rules']=rules;f['households'][0].update(sleep_start=sleep[0],sleep_end=sleep[1],night_start=night[0],night_end=night[1],freshness_minutes=1)
    expected_rows=[dict(zip(FIELDS,['alpha','empty',0,0,0])),dict(zip(FIELDS,['alpha','zone',*expected]))]
    with application(f) as app:
        token=login(app);data=get(app,'report',token,time)
        assert data['as_of']==time and data['window_start']==time-D
        assert projection(data['rooms'],FIELDS)==expected_rows,(data,expected_rows)
        csv_text=request(app,'/api/report.csv?'+urlencode({'household_id':'alpha','as_of':time}),token,raw=True)
        reader=csv.DictReader(io.StringIO(csv_text));assert reader.fieldnames==FIELDS
        decoded=[{k:(int(v) if k.endswith('_count') else v) for k,v in r.items()} for r in reader];assert decoded==expected_rows
        if restart:
            app.stop();app.start();assert projection(get(app,'report',token,time)['rooms'],FIELDS)==expected_rows


def check_6():
    t=BASE+D+12*60*M;lo=t-D
    # Counts include both window endpoints and timestamp ties; sensor state does not deduplicate rows.
    report_case([event('old',lo-1,True),event('left',lo,False),event('sleep-start',BASE+23*60*M,True),event('sleep-end',BASE+D+7*60*M,False),event('right-a',t,True),event('right-z',t,False),event('future',t+1,True)],[],t,(5,1,0),restart=True)
    # Old onset crosses threshold exactly at the left edge; ended intervals still count.
    report_case([event('start',lo-M,True),event('end',lo+1,False)], [rule(threshold=1)],t,(1,0,1))
    # Ending at the threshold excludes that instant. Starting later forms a new episode at right edge.
    report_case([event('first',lo,True),event('end',lo+M,False),event('second',t-M,True)], [rule(threshold=1)],t,(3,0,1))
    # Repeated true observations and several eligible nights remain one episode, whose first trigger is too old here.
    report_case([event('start',BASE,True),event('repeat',BASE+D,True)], [rule('exterior_open_night',30)],BASE+3*D,(0,0,0))
    report_case([event('start',BASE+21*60*M,True),event('end',BASE+22*60*M,False)], [rule('exterior_open_night',30)],BASE+D,(2,0,0))
    # Clock opens after duration has already elapsed, then state closes; staleness does not erase history.
    report_case([event('start',BASE+21*60*M,True),event('end',BASE+22*60*M+1,False)], [rule('exterior_open_night',30)],BASE+D,(2,0,1))
    report_case([event('start',lo,True)], [rule(threshold=1,enabled=False)],t,(1,0,0))
    report_case([event('start',lo,True)], [rule(threshold=1440)],t,(1,0,1))
    report_case([event('start',lo,True)], [rule(threshold=0)],t,(1,0,1),sleep=(100,100))
    report_case([event('before',BASE+9*60*M-1,False),event('start',BASE+9*60*M,False),event('end-before',BASE+17*60*M-1,False),event('end',BASE+17*60*M,False)], [],BASE+D,(4,2,0),sleep=(540,1020))
    report_case([event('z',lo,False,'presence'),event('a',lo,True,'presence'),event('repeat',lo+M,False,'presence')], [rule('no_occupancy',1,'presence')],t,(3,0,1))
    report_case([event('first',lo,True),event('repeat',lo+M,True)], [rule(threshold=1440)],t,(2,0,1))
    report_case([event('first',BASE+5*60*M,True,'presence'),event('end',BASE+6*60*M+1,False,'presence')], [rule('bathroom_occupied_day',30,'presence')],BASE+D,(2,2,1))
    report_case([event('first',lo,True,'presence')], [rule('bathroom_occupied_night',1,'presence')],t,(1,0,0),night=(300,300))
    f=fixture();f['clock_ms']=t;f['events']=[event('onset',lo,True)];f['rules']=[rule(threshold=1)]
    with application(f) as app:
        token=login(app,'helper')
        assert get(app,'alerts',token,t)['alerts']==[]
        assert get(app,'report',token,t)['rooms'][1]['alert_count']==1
        request(app,'/api/rules',token,rule(enabled=False),'PUT');assert get(app,'report',token,t)['rooms'][1]['alert_count']==0
        request(app,'/api/rules',token,rule(threshold=1440),'PUT');assert get(app,'report',token,t)['rooms'][1]['alert_count']==1
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page(accept_downloads=True);ui_login(page,app)
                with page.expect_download() as pending:page.locator('#download').click()
                download=pending.value;assert download.suggested_filename=='activity-report.csv'
                rows=list(csv.DictReader(io.StringIO(Path(download.path()).read_text())));assert rows[1]['alert_count']=='1' and rows[1]['event_count']=='1'
                def fail(route):route.fulfill(status=503,content_type='application/json',body='{"error":{"code":"temporary_report_failure"}}')
                # Transport interception supplies only a failure. Success is fetched from the actual application.
                page.route('**/api/report.csv?*',fail);page.locator('#download').click()
                expect(page.locator('#download-status')).to_contain_text(re.compile('fail|error|unable|unavailable',re.I))
                page.unroute('**/api/report.csv?*',fail)
                with page.expect_download() as pending:page.locator('#download').click()
                assert pending.value.failure() is None
            finally:browser.close()


def main():
    results=[];infra=[];chosen=os.environ.get('MONITOR_GATE')
    for i,test in enumerate([check_1,check_2,check_3,check_4,check_5,check_6],1):
        if chosen and str(i)!=chosen:continue
        try:test();result={'ru_id':f'RU-{i:03d}','passed':True}
        except (AssertionError,CandidateFailure,BrowserTimeout,KeyError,IndexError) as e:
            traceback.print_exc(file=sys.stderr);result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(e)[-1800:] or type(e).__name__}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            if type(e).__name__=='CandidateFailure':result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(e)[-1800:]}
            else:infra.append(f'RU-{i:03d}: {type(e).__name__}: {e}');result={'ru_id':f'RU-{i:03d}','passed':False,'detail':'Unattributed evaluator error'}
        results.append(result)
    print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}));return 2 if infra else 0


if __name__=='__main__':raise SystemExit(main())
