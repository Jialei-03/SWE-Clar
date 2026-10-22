"""Independent acceptance of the frozen five-RU browser/HTTP monitoring contract."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from urllib.parse import urlencode,urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parent))
from monitor_support import application,request,rows,business,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
csv.field_size_limit(1048576)


def fixture():
    return {'accounts':[{'id':key,'name':name,'password':'independent-pass'} for key,name in [('one','Analyst <one>'),('two','Analyst two')]],
            'competitors':[{'account_id':'one','competitor_id':key,'name':name,'archived':archived,'urls':urls} for key,name,archived,urls in [('a','Straße alpha',False,['/pages/page-one','/pages/page-two']),('b','Second item',False,['/pages/page-two']),('old','Archived sample',True,['/pages/page-one'])]]+ [{'account_id':'two','competitor_id':'a','name':'Other account item','archived':False,'urls':['/pages/page-one']}],
            'subscriptions':[{'account_id':key,'sequence':0,'plan':'full','status':'active'} for key in ['one','two']]}


def get(app,path,token,**query):return request(app,'/api/'+path+('?' +urlencode(query) if query else ''),token)
def post(app,path,token,body,status=200):return request(app,'/api/'+path,token,body,status)
def login(app,key='one'):return post(app,'login',None,{'id':key,'password':'independent-pass'})['token']
def url_id(app,token,key='a',index=0):return get(app,'competitor',token,competitor_id=key)['urls'][index]['url_id']
def take(app,token,url,key,when,status=200):return post(app,'snapshots',token,{'snapshot_id':key,'url_id':url,'observed_at_ms':when},status)
def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def project(values,keys):return [{k:r[k] for k in keys} for r in values]
def receipt(app,key,sequence,status='active',plan='full',account='one',**kwargs):
    value={'id':key,'account_id':account,'sequence':sequence,'plan':plan,'status':status}
    app.provider.set_receipt(key,value,**kwargs);return value
def apply(app,token,key,status=200):return post(app,'subscription',token,{'receipt_id':key},status)


def sign_in(page,app,key='one',navigate=True):
    if navigate:page.goto(app.url)
    page.locator('#account').fill(key);page.locator('#password').fill('independent-pass');page.locator('#login-form button').click()
    expect(page.locator('#identity')).to_contain_text('Analyst <one>' if key=='one' else 'Analyst two')
    expect(page.locator('[data-competitor-id]').first).to_be_visible()


class Held:
    def __init__(self,page,path):
        self.page,self.path,self.held=page,path,None
        page.route('**/api/*',self.capture)
    def capture(self,route):
        if urlsplit(route.request.url).path==self.path and self.held is None:self.held=(route,route.fetch())
        else:route.continue_()
    def wait(self):
        deadline=time.monotonic()+5
        while self.held is None and time.monotonic()<deadline:self.page.wait_for_timeout(20)
        assert self.held is not None,'Required actual browser request missing'
        assert self.held[1].status==200,'Hold only an actual successful response'
    def release(self):
        route,response=self.held;route.fulfill(response=response)
        self.page.wait_for_timeout(150)
        self.page.unroute('**/api/*',self.capture)


def watch(page,selector,needle):
    page.evaluate('''([selector,needle])=>{window.flashes=[];window.observer=new MutationObserver(()=>{const text=document.querySelector(selector).textContent;if(text.includes(needle))flashes.push(text);});observer.observe(document.querySelector(selector),{subtree:true,childList:true,characterData:true});}''',[selector,needle])


def no_flash(page):
    assert page.evaluate('flashes')==[],'A stale response briefly rendered old context'
    page.evaluate('observer.disconnect()')


def check_1():
    with application(fixture()) as app:
        for key,password in [('one','wrong'),('missing','independent-pass')]:post(app,'login',None,{'id':key,'password':password},401)
        token=login(app);other=login(app,'two');another=login(app)
        for bad in [None,'one','two','forged']:
            for endpoint in ['me','competitors','subscription','history?url_id=fake']:
                request(app,'/api/'+endpoint,bad,status=401)
        account=get(app,'me',token)['account'];assert project([account],['id','name'])==[{'id':'one','name':'Analyst <one>'}]
        for endpoint in ['me','competitors','competitor?competitor_id=a']:
            output=json.dumps(request(app,'/api/'+endpoint,token));assert all(value not in output for value in ['independent-pass','password',other,another])
        for body in [b'{"id":"one","id":"two","password":"independent-pass"}',b'{"id":"one","password":NaN}']:
            request(app,'/api/login',status=400,raw_body=body)
        post(app,'logout',token,{});request(app,'/api/me',token,status=401);assert get(app,'me',another)['account']['id']=='one'
        before=rows(app,'competitors');app.stop();app.start();assert rows(app,'competitors')==before
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();sign_in(page,app)
                assert page.locator('#identity one').count()==0
                for w,h in [(390,844),(1280,900)]:page.set_viewport_size({'width':w,'height':h});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                held=Held(page,'/api/competitors');page.locator('#refresh').click();held.wait()
                page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden()
                assert 'Straße alpha' not in page.locator('#application').text_content()
                sign_in(page,app,'two',False);watch(page,'#application','Straße alpha');held.release();no_flash(page)
                assert 'Straße alpha' not in page.locator('#application').inner_text()
            finally:browser.close()


def check_2():
    with application(fixture()) as app:
        token,other=login(app),login(app,'two')
        assert [r['competitor_id'] for r in get(app,'competitors',token)['competitors']]==['b','a']
        assert [r['competitor_id'] for r in get(app,'competitors',token,status='archive')['competitors']]==['old']
        assert [r['competitor_id'] for r in get(app,'competitors',token,q='STRASSE')['competitors']]==['a']
        assert len(get(app,'competitors',token,status='all')['competitors'])==3
        body={'competitor_id':'new','name':'  alpha <b>label</b>  ','urls':[app.provider.url.upper()+'/pages/page-two?x=2#fragment',app.provider.url+'/pages/page-one?x=1']}
        result=post(app,'competitors',token,body)['competitor'];assert result['name']=='alpha <b>label</b>' and result['archived'] is False
        created=get(app,'competitor',token,competitor_id='new')['urls']
        assert [u['url'] for u in created]==[app.provider.url+'/pages/page-two?x=2',app.provider.url+'/pages/page-one?x=1']
        assert len({u['url_id'] for u in created})==2
        assert all(u[k] is None for u in created for k in ['text','sha256','observed_at_ms'])
        post(app,'competitors',token,body,409)
        post(app,'competitors',other,body)
        for bad in [{**body,'competitor_id':'z','name':name} for name in ['', ' ',True,'n'*121]]+[{**body,'competitor_id':'z','account_id':'two'},{**body,'competitor_id':'z','archived':True},{**body,'competitor_id':'z','urls':[]}]:post(app,'competitors',token,bad,400)
        urls=[app.provider.url+'/pages/page-one#f',app.provider.url+'/pages/page-one']
        post(app,'competitors',token,{**body,'competitor_id':'z','urls':urls},400)
        for url in ['https://127.0.0.1/pages/page-one','http://external.invalid/pages/page-one',app.provider.url+'/health',app.provider.url+'/pages/%70age-one',app.provider.url+'/pages/page-one x',app.provider.url.replace('://','://u@')+'/pages/page-one',app.provider.url+'/pages/page-one?'+('q'*2048)]:post(app,'competitors',token,{**body,'competitor_id':'z','urls':[url]},400)
        longest=app.provider.url+'/pages/page-one?';longest+='x'*(2048-len(longest))
        maximum={'competitor_id':'m'*64,'name':'N'*120,'urls':[longest]+[app.provider.url+'/pages/page-one?index='+str(i) for i in range(9)]}
        post(app,'competitors',token,maximum)
        assert len(get(app,'competitor',token,competitor_id='m'*64)['urls'])==10
        request(app,'/api/competitor?competitor_id=old',other,status=404)
        request(app,'/api/competitors?status=active&status=archive',token,status=400)
        request(app,'/api/competitors?status=invalid',token,status=400)
        before=rows(app,'urls');app.stop();app.start();assert rows(app,'urls')==before
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();sign_in(page,app)
                held=Held(page,'/api/competitor');page.locator('[data-competitor-id="a"] button').click();held.wait()
                page.locator('[data-competitor-id="b"] button').click();expect(page.locator('#competitor-detail')).to_contain_text('Second item')
                watch(page,'#competitor-detail','Straße alpha');held.release();no_flash(page)
                expect(page.locator('#competitor-detail')).to_contain_text('Second item')
            finally:browser.close()


def check_3():
    with application(fixture()) as app:
        token,other=login(app),login(app,'two');url=url_id(app,token);second=url_id(app,token,index=1)
        cases=[
            (b'<!doctype html><html><head><title>Omit</title></head><body><p>A&amp;<b>B</b></p><div>C<br>D</div><script>omit</script><style>omit</style><template>omit</template><noscript>omit</noscript><!--omit--></body></html>','A&B C D'),
            (b'<p>A&#38;B</p><div> C <br> D </div>','A&B C D'),
            ('<p>café\u00a0next\tline</p><span hidden>retained</span><span style="display:none">!</span>'.encode(),'café next line retained!'),
            (b'\xef\xbb\xbf<table><tr><td>One</td><td>Two</td></tr></table>','One Two'),
            (b'<script>only omitted text</script>',''),
            (b'x','x'),
            (b'y'*262144,'y'*262144),
            (b'<p>Quoted &quot;value&quot;, &lt;b&gt;literal&lt;/b&gt;</p>','Quoted "value", <b>literal</b>'),
        ]
        previous=None;events=[]
        for when,(html,expected) in enumerate(cases):
            app.provider.set_page('page-one',html,content_type='Text/HTML; charset=UTF-8')
            before_count=len(app.provider.requests())
            data=take(app,token,url,'snap-'+str(when),when)
            assert len(app.provider.requests())>before_count,'Snapshot did not actually read the registered HTTP resource'
            assert data['duplicate'] is False
            assert project([data['snapshot']],['snapshot_id','url_id','observed_at_ms','text','sha256'])==[{'snapshot_id':'snap-'+str(when),'url_id':url,'observed_at_ms':when,'text':expected,'sha256':sha(expected)}]
            if previous is not None and previous!=expected:events.append({'snapshot_id':'snap-'+str(when),'url_id':url,'observed_at_ms':when,'before_text':previous,'after_text':expected,'before_sha256':sha(previous),'after_sha256':sha(expected)})
            assert project(get(app,'history',token,url_id=url)['events'],['snapshot_id','url_id','observed_at_ms','before_text','after_text','before_sha256','after_sha256'])==events
            assert len(rows(app,'snapshots'))==when+1
            previous=expected
        stored=business(app);count=len(app.provider.requests())
        duplicate=take(app,token,url,'snap-0',0);assert duplicate['duplicate'] is True and duplicate['snapshot']['text']=='A&B C D'
        assert len(app.provider.requests())==count and business(app)==stored
        take(app,token,url,'snap-0',1,409);take(app,token,second,'snap-0',0,409)
        take(app,token,url,'equal-time',7,409);take(app,token,url,'old-time',6,409)
        take(app,other,url,'foreign',8,404);assert len(app.provider.requests())==count
        for value in [True,-1,1.5,253402300800000,'later']:
            take(app,token,url,'invalid',value,400)
        for extra in ['html','content_hash','account_id']:
            post(app,'snapshots',token,{'snapshot_id':'invalid','url_id':url,'observed_at_ms':10,extra:'untrusted'},400)
        invalid=[(b'',{}),(b'z'*262145,{}),(b'\xff',{}),(b'a\x00b',{}),(b'failed',{'status':503}),(b'<p>json type</p>',{'content_type':'application/json'}),(b'<p>compressed</p>',{'headers':(('Content-Encoding','gzip'),)}),(b'redirect',{'status':302,'headers':(('Location',app.provider.url+'/pages/page-two'),)})]
        for case,(html,kwargs) in enumerate(invalid):
            app.provider.set_page('page-one',html,**kwargs)
            try:take(app,token,url,'failure-retry',10,502);assert business(app)==stored
            except AssertionError as error:raise CandidateFailure(f'Provider fault case {case}, bytes={len(html)}, options={kwargs}: {error}') from error
        handler=app.provider.server.RequestHandlerClass;normal_response=handler.respond
        def interrupted_response(self,resource):
            if resource.body==b'private-truncated-resource':
                self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length','20');self.end_headers();self.wfile.write(b'<p>');self.close_connection=True
            else:normal_response(self,resource)
        app.provider.set_page('page-one',b'private-truncated-resource');handler.respond=interrupted_response
        try:take(app,token,url,'failure-retry',10,502)
        finally:handler.respond=normal_response
        assert business(app)==stored
        assert not any(r['path']=='/pages/page-two' for r in app.provider.requests()),'Redirect target was fetched'
        entered,release=threading.Event(),threading.Event()
        app.provider.set_page('page-one','<p>Not released before timeout</p>',entered=entered,release=release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(take,app,token,url,'failure-retry',10,502)
            try:
                assert entered.wait(3);pending.result(timeout=8)
            finally:release.set()
        assert business(app)==stored
        app.provider.set_page('page-one','<p>Recovered</p>');take(app,token,url,'failure-retry',10)
        app.provider.set_page('page-one','<p>Concurrent</p>')
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:take(app,token,url,'concurrent',11),range(6)))
        assert sum(r['duplicate'] is False for r in results)==1
        assert len([r for r in rows(app,'snapshots') if r['snapshot_id']=='concurrent'])==1
        take(app,other,url_id(app,other),'snap-0',0)
        entered,release=threading.Event(),threading.Event()
        app.provider.set_page('page-one','<p>Old response</p>',entered=entered,release=release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            old=pool.submit(take,app,token,url,'older',12,409)
            try:
                assert entered.wait(3);app.provider.set_page('page-one','<p>New response</p>');take(app,token,url,'newer',13)
            finally:release.set()
            old.result(timeout=7)
        app.provider.set_page('page-one','<p>Last permitted time</p>');take(app,token,url,'last',253402300799999)
        before=business(app);app.stop();app.start();assert business(app)==before
        raw,headers=request(app,'/api/history.csv?'+urlencode({'url_id':url}),token,raw=True)
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8')));columns=['snapshot_id','observed_at_ms','before_text','after_text','before_sha256','after_sha256'];assert reader.fieldnames==columns
        assert list(reader)==[{k:str(r[k]) for k in columns} for r in get(app,'history',token,url_id=url)['events']]
        assert 'changes.csv' in headers.get('Content-Disposition','')
        for endpoint in ['history','history.csv']:request(app,'/api/'+endpoint+'?url_id='+url,other,status=404)
    extraction_boundaries()
    browser_snapshots()


def extraction_boundaries():
    with application(fixture()) as app:
        token=login(app);url=url_id(app,token)
        tags='address article aside blockquote dd div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header li main nav ol p pre section table tbody td tfoot th thead tr ul'.split()
        for i,tag in enumerate(tags):
            app.provider.set_page('page-one','A<'+tag+'>B</'+tag+'>C')
            assert take(app,token,url,'block-'+tag,i)['snapshot']['text']=='A B C'
        app.provider.set_page('page-one','A<hr>B<br>C<span>D</span><i>E</i><template><div>omit</div><template>also omit</template></template>F')
        assert take(app,token,url,'inline',100)['snapshot']['text']=='A B CDEF'


def browser_snapshots():
    with application(fixture()) as app:
        token=login(app);url=url_id(app,token)
        app.provider.set_page('page-one','<p>Original browser text</p>');take(app,token,url,'prior',0)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();sign_in(page,app)
                page.locator('[data-competitor-id="a"] button').click();page.locator('[data-url-id] button').first.click()
                expect(page.locator('#url-detail')).to_contain_text('Original browser text')
                page.locator('#snapshot-id').fill('browser');page.locator('#snapshot-time').fill('1970-01-01T00:00:01Z')
                app.provider.set_page('page-one','unavailable',status=503)
                with page.expect_response(lambda r:'/api/snapshots' in r.url):page.locator('#snapshot-save').click()
                expect(page.locator('#url-detail')).to_contain_text('Original browser text')
                assert page.locator('#snapshot-id').input_value()=='browser'
                app.provider.set_page('page-one','<p>Browser &lt;img&gt;, &quot;literal&quot; café</p>')
                page.locator('#snapshot-save').click();expect(page.locator('#url-detail')).to_contain_text('Browser <img>, "literal" café')
                assert page.locator('#url-detail img,#history img').count()==0
                expect(page.locator('#history')).to_contain_text('Original browser text')
                expect(page.locator('#history')).to_contain_text('Browser <img>, "literal" café')
                with page.expect_download() as pending:page.locator('#history-download').click()
                downloaded=list(csv.DictReader(io.StringIO(Path(pending.value.path()).read_text())));assert downloaded[0]['after_text']=='Browser <img>, "literal" café'
                held=Held(page,'/api/history');page.locator('[data-url-id] button').first.click();held.wait()
                page.locator('[data-url-id] button').nth(1).click();expect(page.locator('#url-detail')).to_contain_text('/pages/page-two')
                watch(page,'#history','Original browser text');held.release();no_flash(page)
            finally:browser.close()


def check_4():
    with application(fixture()) as app:
        token,other=login(app),login(app,'two');url=url_id(app,token)
        take(app,token,url,'initial',0);app.provider.set_page('page-one','<p>Changed once</p>');take(app,token,url,'changed',1)
        before=business(app)
        post(app,'archive',other,{'competitor_id':'b','archived':True},404)
        for body in [{'competitor_id':'a','archived':1},{'competitor_id':'a','archived':True,'account_id':'two'}]:post(app,'archive',token,body,400)
        post(app,'archive',token,{'competitor_id':'a','archived':True});post(app,'archive',token,{'competitor_id':'a','archived':True})
        assert [r['competitor_id'] for r in get(app,'competitors',token)['competitors']]==['b']
        count=len(app.provider.requests());take(app,token,url,'denied',2,409);assert len(app.provider.requests())==count
        assert take(app,token,url,'initial',0)['duplicate'] is True
        assert get(app,'history',token,url_id=url)['events'][0]['snapshot_id']=='changed'
        request(app,'/api/history.csv?url_id='+url,token,raw=True)
        for table in ['urls','snapshots','events']:assert rows(app,table)==before[table]
        post(app,'archive',token,{'competitor_id':'a','archived':False})
        entered,release=threading.Event(),threading.Event();app.provider.set_page('page-one','<p>Held lifecycle response</p>',entered=entered,release=release)
        before=business(app)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(take,app,token,url,'race',2,409)
            try:
                assert entered.wait(3)
                post(app,'archive',token,{'competitor_id':'a','archived':True})
                post(app,'archive',token,{'competitor_id':'a','archived':False})
            finally:release.set()
            pending.result(timeout=7)
        assert business(app)==before;take(app,token,url,'race',2)
        before=business(app);app.stop();app.start();assert business(app)==before
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();sign_in(page,app);page.locator('[data-competitor-id="a"] button').click()
                page.locator('[data-url-id] button').first.click();page.locator('#archive').click()
                expect(page.locator('#restore')).to_be_enabled();expect(page.locator('#snapshot-save')).to_be_disabled()
                assert get(app,'competitor',token,competitor_id='a')['competitor']['archived'] is True
                page.locator('#restore').click();expect(page.locator('#archive')).to_be_enabled();expect(page.locator('#snapshot-save')).to_be_enabled()
                assert get(app,'competitor',token,competitor_id='a')['competitor']['archived'] is False
            finally:browser.close()


def check_5():
    with application(fixture()) as app:
        token,other=login(app),login(app,'two');url=url_id(app,token)
        take(app,token,url,'existing',0);receipt(app,'cancel',1,'cancelled');receipt(app,'restore',2)
        count=len(app.provider.requests());assert apply(app,token,'cancel')['writable'] is False
        assert len(app.provider.requests())>count
        preserved={table:rows(app,table) for table in ['urls','snapshots','events']}
        count=len(app.provider.requests());take(app,token,url,'inactive',1,403);assert len(app.provider.requests())==count
        assert take(app,token,url,'existing',0)['duplicate'] is True
        post(app,'competitors',token,{'competitor_id':'inactive','name':'Inactive','urls':[app.provider.url+'/pages/page-one']},403)
        post(app,'archive',token,{'competitor_id':'a','archived':True});post(app,'archive',token,{'competitor_id':'a','archived':False},403)
        # Approved precedence: nonwritable access wins over archived for a NEW snapshot.
        overlap_before=business(app);overlap_requests=len(app.provider.requests())
        take(app,token,url,'inactive-and-archived',1,403)
        assert business(app)==overlap_before and len(app.provider.requests())==overlap_requests
        assert take(app,token,url,'existing',0)['duplicate'] is True
        assert get(app,'competitor',token,competitor_id='a')['urls'];get(app,'history',token,url_id=url);request(app,'/api/history.csv?url_id='+url,token,raw=True)
        assert apply(app,token,'restore')['writable'] is True
        assert apply(app,token,'cancel')['duplicate'] is True
        assert get(app,'subscription',token)['subscription']['sequence']==2
        receipt(app,'cancel',1,'payment_failed');apply(app,token,'cancel',409)
        receipt(app,'same-sequence',2);apply(app,token,'same-sequence',409)
        receipt(app,'old-sequence',1);apply(app,token,'old-sequence',409)
        receipt(app,'foreign',3,account='two');apply(app,token,'foreign',403)
        for key,sequence,plan,status in [('basic',3,'basic','active'),('failed',4,'full','payment_failed'),('cancelled',5,'full','cancelled'),('full',6,'full','active')]:
            receipt(app,key,sequence,status,plan);result=apply(app,token,key);assert result['writable'] is (plan=='full' and status=='active')
        for table,saved in preserved.items():assert rows(app,table)==saved
        post(app,'archive',token,{'competitor_id':'a','archived':False})
        before=business(app)
        for body in [{'receipt_id':'forged','status':'active'},{'receipt_id':'forged','provider_url':app.provider.url},{'receipt_id':True}]:post(app,'subscription',token,body,400)
        apply(app,token,'unknown',404)
        good={'id':'bad','account_id':'one','sequence':7,'plan':'full','status':'active'}
        bad_records=[{**good,'sequence':x} for x in [True,0,-1,1.5,2147483648]]+[{**good,'plan':'premium'},{**good,'status':'paid'},{**good,'id':'different'},{**good,'extra':1},{k:v for k,v in good.items() if k!='status'},[],{'id':'bad'},'{"id":"bad","id":"bad"}']
        bad_records.append(json.dumps(good).replace('"id": "bad"','"id": "bad", "id": "bad"'))
        for body in bad_records:
            if isinstance(body,list):body=json.dumps(body)
            app.provider.set_receipt('bad',body);apply(app,token,'bad',502);assert business(app)==before
        padded=json.dumps(good).encode().ljust(16385,b' ')
        for body,kwargs in [(b'',{}),(padded,{}),(b'\xff',{}),(json.dumps(good).encode(),{'content_type':'text/html'}),(json.dumps(good).encode(),{'headers':(('Content-Encoding','gzip'),)}),(b'failed',{'status':503}),(b'moved',{'status':302,'headers':(('Location',app.provider.url+'/v1/receipts/full'),)})]:
            app.provider.set_receipt('bad',body,**kwargs);apply(app,token,'bad',502);assert business(app)==before
        app.provider.set_receipt('bad',json.dumps(good).encode().ljust(16384,b' '));apply(app,token,'bad')
        entered,release=threading.Event(),threading.Event()
        receipt(app,'slow-old',7,'cancelled',entered=entered,release=release);receipt(app,'fast-new',8)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(apply,app,token,'slow-old',409)
            try:assert entered.wait(3);apply(app,token,'fast-new')
            finally:release.set()
            pending.result(timeout=7)
        receipt(app,'duplicate',9)
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:apply(app,token,'duplicate'),range(6)))
        assert sum(r['duplicate'] is False for r in results)==1
        receipt(app,'revoke-during',10,'cancelled');receipt(app,'restore-during',11)
        entered,release=threading.Event(),threading.Event();app.provider.set_page('page-one','<p>Billing race</p>',entered=entered,release=release)
        before={table:rows(app,table) for table in ['urls','snapshots','events']}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(take,app,token,url,'billing-race',1,409)
            try:assert entered.wait(3);apply(app,token,'revoke-during');apply(app,token,'restore-during')
            finally:release.set()
            pending.result(timeout=7)
        for table,saved in before.items():assert rows(app,table)==saved
        take(app,token,url,'billing-race',1)
        receipt(app,'renewal-only',12)
        entered,release=threading.Event(),threading.Event();app.provider.set_page('page-one','<p>Renewal permits commit</p>',entered=entered,release=release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(take,app,token,url,'renewal-observation',2)
            try:
                assert entered.wait(3);apply(app,token,'restore-during');apply(app,token,'renewal-only')
                post(app,'archive',token,{'competitor_id':'a','archived':False})
            finally:release.set()
            pending.result(timeout=7)
        receipt(app,'last-sequence',2147483647);apply(app,token,'last-sequence')
        before=business(app);app.stop();app.start();assert business(app)==before
        assert get(app,'subscription',token)['subscription']['sequence']==2147483647
    browser_billing()


def browser_billing():
    with application(fixture()) as app:
        token=login(app);receipt(app,'browser-cancel',1,'cancelled');receipt(app,'browser-restore',2)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();sign_in(page,app)
                page.locator('[data-competitor-id="a"] button').click();page.locator('[data-url-id] button').first.click()
                page.locator('#receipt-id').fill('browser-cancel');page.locator('#receipt-submit').click()
                expect(page.locator('#competitor-save')).to_be_disabled();expect(page.locator('#snapshot-save')).to_be_disabled()
                assert get(app,'subscription',token)['writable'] is False
                page.locator('#receipt-id').fill('browser-restore');page.locator('#receipt-submit').click()
                expect(page.locator('#snapshot-save')).to_be_enabled();assert get(app,'subscription',token)['writable'] is True
                old_summary=page.locator('#subscription-summary').inner_text();held=Held(page,'/api/subscription');page.locator('#receipt-id').fill('browser-cancel');page.locator('#receipt-submit').click();held.wait()
                page.locator('#logout').click();sign_in(page,app,'two',False)
                expect(page.locator('#subscription-summary')).to_contain_text('0')
                new_summary=page.locator('#subscription-summary').inner_text();watch(page,'#subscription-summary',old_summary);held.release();no_flash(page)
                assert page.locator('#subscription-summary').inner_text()==new_summary
            finally:browser.close()


def main():
    results=[];infra=[];chosen=os.environ.get('MONITOR_GATE')
    for i,test in enumerate([check_1,check_2,check_3,check_4,check_5],1):
        if chosen and chosen!=str(i):continue
        try:test();result={'ru_id':f'RU-{i:03d}','passed':True}
        except (AssertionError,CandidateFailure,BrowserTimeout,KeyError,IndexError) as error:
            traceback.print_exc(file=sys.stderr);result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(error)[-1500:] or type(error).__name__}
        except Exception as error:
            traceback.print_exc(file=sys.stderr);infra.append(f'RU-{i:03d}: {type(error).__name__}: {error}');result={'ru_id':f'RU-{i:03d}','passed':False,'detail':'Unattributed evaluator error'}
        results.append(result)
    print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}));return 2 if infra else 0


if __name__=='__main__':raise SystemExit(main())
