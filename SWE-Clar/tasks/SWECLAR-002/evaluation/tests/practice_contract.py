"""Independent behavior checks; candidate code runs under the unprivileged application identity."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json,math,os,re,sys,time,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'/public_tests')
from practice_support import App,CandidateFailure,login_page
from test_public import check as visible_check
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout

PROJECT=os.environ.get('SWECLAR_PROJECT_DIR','/workspace')

def set_choice(page, test_id, value, label=None):
    """Operate an agreed field without imposing an undeclared HTML tag."""
    control=page.get_by_test_id(test_id)
    tag=control.evaluate('(element) => element.tagName.toLowerCase()')
    if tag=='select':
        control.select_option(value=value)
    elif tag in ('input','textarea'):
        control.fill(value)
    else:
        # A named group of real radio controls is an equivalent choice UI.
        # Keep selection inside the agreed test-id boundary. The subsequent
        # activation checks the real selected values and persisted outcome;
        # do not impose an undeclared ARIA-state representation.
        option=control.get_by_role('radio',name=label or value,exact=True)
        assert option.count()==1, f'{test_id}: no unique radio choice for {value}'
        option.click()
        return
    expect(control).to_have_value(value)

def wait_pending(page,requests,n):
    end=time.monotonic()+5
    while len(requests)<n and time.monotonic()<end:page.wait_for_timeout(25)
    assert len(requests)>=n,'Expected browser request did not arrive'

def subscription_mentions(text, product, title, store):
    products=re.findall(r'(?<!\w)(?:'+re.escape(title)+'|'+re.escape(product)+r')(?!\w)',text,re.I)
    channels=re.findall(r'(?<!\w)'+re.escape(store)+r'(?!\w)',text,re.I)
    return len(products),len(channels)

def ru001():
    with App(PROJECT) as a:
        visible_check(a);token=a.login()
        a.request('/goals',{'id':'extra','title':'x','extra':True},token,status=400)
        a.request('/goals',{'id':'x','title':'x'},token,method='PUT',status=405)
        a.request('/login',token=token,status=405)
        a.request('/not-a-route',token=token,status=404)
        a.request('/goals',b'{broken',token,status=400)
        a.request('/goals',b' '*65537,token,status=413)

def ru002():
    with App(PROJECT) as a:
        one=a.login();two=a.login('user-b')
        for channel in ['alpha','beta']:
            action=a.receipt('payment '+channel+'/encoded',store=channel)
            expected={**action,'user':'user-a'};assert a.request('/activate',action,one)==expected
            a.receipts.pop(action['transaction_id']);a.provider_status[action['transaction_id']]=503
            assert a.request('/activate',action,one)==expected and a.provider_hits[action['transaction_id']]==1
            a.request('/activate',action,two,status=409)
            a.request('/activate',{**action,'product':'annual'},one,status=409)
            a.request('/activate',{**action,'store':'beta' if channel=='alpha' else 'alpha'},one,status=409)
        action=a.receipt('simultaneous')
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:a.request('/activate',action,one),range(4)))
        assert all(r=={**action,'user':'user-a'} for r in results)
        rows=a.request('/subscriptions',token=one);assert isinstance(rows,list)
        assert [r['transaction_id'] for r in rows]==['payment alpha/encoded','payment beta/encoded','simultaneous']
        assert a.request('/subscriptions',token=two)==[]
        baseline=rows
        for name,extra in [('wrong-user',{'user':'user-b'}),('pending',{'status':'pending'}),('wrong-product',{'product':'annual'}),('wrong-channel',{'store':'beta'}),('wrong-tx',{'transaction_id':'other'})]:
            action=a.receipt(name,**extra);action.update(transaction_id=name,product='quarter',store='alpha');a.request('/activate',action,one,status=400)
        action=a.receipt('unsigned');a.receipts['unsigned']['signature']='0'*64;a.request('/activate',action,one,status=400)
        for index,body in enumerate([b'{bad',{},[],{'payload':{},'signature':42}]):
            name='malformed-'+str(index);a.receipts[name]=body;a.request('/activate',{'transaction_id':name,'product':'quarter','store':'alpha'},one,status=400)
        for name,status,want in [('missing',404,400),('offline',503,502)]:
            a.provider_status[name]=status;a.request('/activate',{'transaction_id':name,'product':'quarter','store':'alpha'},one,status=want)
        a.request('/activate',{'transaction_id':'x','product':'quarter','store':'other'},one,status=400)
        assert a.request('/subscriptions',token=one)==baseline
        a.stop();a.start();assert a.request('/subscriptions',token=one)==baseline
        assert a.request('/activate',{'transaction_id':'payment alpha/encoded','product':'quarter','store':'alpha'},one)['user']=='user-a'
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,a);page.get_by_test_id('tab-subscription').click()
                title=a.config['products']['quarter']['title']
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    before=subscription_mentions(page.locator('body').inner_text(),'quarter',title,'alpha')
                    if before[0]>=3 and before[1]>=2:break
                    page.wait_for_timeout(25)
                assert before[0]>=3 and before[1]>=2, 'Saved subscriptions must be displayed before the new activation'
                a.receipt('browser');set_choice(page,'product','quarter',label=title);set_choice(page,'store','alpha');page.get_by_test_id('transaction').fill('browser');page.get_by_test_id('activate').click()
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    after=subscription_mentions(page.locator('body').inner_text(),'quarter',title,'alpha')
                    if after==(before[0]+1,before[1]+1):break
                    page.wait_for_timeout(25)
                assert after==(before[0]+1,before[1]+1), 'Activation must add visible product/channel information'
                assert any(r=={'transaction_id':'browser','product':'quarter','store':'alpha'} for r in a.request('/subscriptions',token=one))
            finally:browser.close()

def ru003():
    app=App(PROJECT);app.config['tracks'].append({'id':'orphan','title':'Unlisted','filename':'tone-a.wav','playlists':[]})
    with app as a:
        token=a.login();assert [r['id'] for r in a.request('/tracks',token=token)]==['tone-a','tone-b']
        wav=Path(os.environ['PRACTICE_ASSETS'],'tone-a.wav').read_bytes();body,headers=a.request('/audio/tone-a',token=token,raw=True);assert body==wav and headers['Content-Type']=='audio/wav'
        for value,start,end in [('bytes=0-15',0,15),('bytes=30-',30,len(wav)-1),('bytes=20-9999999',20,len(wav)-1)]:
            body,headers=a.request('/audio/tone-a',token=token,status=206,raw=True,headers={'Range':value});assert body==wav[start:end+1];assert headers['Content-Range']==f'bytes {start}-{end}/{len(wav)}'
        for value in ['bytes=20-10','bytes=-20','bytes=0-1,3-4','bytes=9999999-']:a.request('/audio/tone-a',token=token,status=416,headers={'Range':value})
        a.request('/audio/tone-a',status=401);a.request('/audio/orphan',token=token,status=404)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,a);page.get_by_test_id('resume').click();expect(page.get_by_test_id('error')).to_have_text('')
                page.get_by_test_id('play-tone-a').click();page.wait_for_function("document.querySelector('audio').currentTime>.2")
                page.get_by_test_id('pause').click();position=page.locator('audio').evaluate('(a)=>a.currentTime');page.wait_for_timeout(250);assert abs(page.locator('audio').evaluate('(a)=>a.currentTime')-position)<.08
                page.get_by_test_id('resume').click();page.wait_for_function('(v)=>document.querySelector("audio").currentTime>v+.2',arg=position)
                page.get_by_test_id('tab-goals').click();position=page.locator('audio').evaluate('(a)=>a.currentTime');page.wait_for_function('(v)=>document.querySelector("audio").currentTime>v+.2',arg=position);page.get_by_test_id('tab-audio').click()
                pending=[];page.route('**/audio/**',lambda route:pending.append(route))
                page.get_by_test_id('play-tone-b').click();wait_pending(page,pending,1);assert page.locator('audio').evaluate('(a)=>a.paused&&!a.hasAttribute("src")')
                page.get_by_test_id('play-tone-a').click();wait_pending(page,pending,2)
                pending[1].fulfill(status=200,content_type='audio/wav',body=wav);page.wait_for_function("document.querySelector('audio').currentTime>.2");source=page.locator('audio').evaluate('(a)=>a.src')
                pending[0].fulfill(status=200,content_type='audio/wav',body=Path(os.environ['PRACTICE_ASSETS'],'tone-b.wav').read_bytes());page.wait_for_timeout(250);assert page.locator('audio').evaluate('(a)=>a.src')==source
                page.get_by_test_id('play-tone-b').click();wait_pending(page,pending,3);page.get_by_test_id('pause').click();pending[2].fulfill(status=200,content_type='audio/wav',body=wav);page.wait_for_timeout(250);assert page.locator('audio').evaluate('(a)=>a.paused&&!a.hasAttribute("src")')
                page.get_by_test_id('play-tone-a').click();wait_pending(page,pending,4);page.get_by_test_id('logout').click();pending[3].abort();page.wait_for_timeout(250)
                assert page.locator('audio').evaluate('(a)=>a.paused&&!a.hasAttribute("src")');expect(page.get_by_test_id('error')).to_have_text('')
            finally:browser.close()

def ru004():
    with App(PROJECT) as a:
        one=a.login();two=a.login('user-b');empty={'count':0,'latest':{},'overall':{}}
        assert a.request('/report',token=one)==empty
        for token,title in [(one,'  First goal  '),(two,'Second goal')]:a.request('/goals',{'id':'shared','title':title},token)
        a.request('/goals',{'id':'shared','title':'overwrite'},one,status=409)
        assert a.request('/goals',token=one)==[{'id':'shared','title':'First goal','complete':0}]
        for _ in range(2):assert a.request('/complete-goal',{'id':'shared'},one)=={'id':'shared','complete':True}
        assert a.request('/report',token=one)==empty and a.request('/goals',token=two)[0]['complete']==0
        a.request('/goals',{'id':'only-b','title':'Private B'},two);a.request('/complete-goal',{'id':'only-b'},one,status=404)
        q=[r['id'] for r in a.config['questions']];first=dict(zip(q,[0,1,2,3,4,10]));second=dict(zip(q,[10,8,6,4,2,0]))
        for answer in [first,second,second]:a.request('/surveys',{'answers':answer},one)
        report=a.request('/report',token=one);assert isinstance(report,dict) and set(report)=={'count','latest','overall'} and report['count']==3 and report['latest']==second
        for key in q:assert isinstance(report['overall'][key],(int,float)) and math.isclose(report['overall'][key],(first[key]+2*second[key])/3,abs_tol=1e-8)
        assert a.request('/report',token=two)==empty
        for answer in [{},dict(first,extra=1),{**first,q[0]:True},{**first,q[0]:None},{**first,q[0]:'2'},{**first,q[0]:-0.01},{**first,q[0]:10.01},{**first,q[0]:float('nan')},{**first,q[0]:float('inf')},{**first,q[0]:10**500}]:a.request('/surveys',{'answers':answer},one,status=400)
        assert a.request('/report',token=one)==report
        for data in [{'id':'bad id','title':'x'},{'id':'x','title':' '},{'id':'x','title':'x'*121}]:a.request('/goals',data,one,status=400)
        a.stop();a.start();assert a.request('/report',token=one)==report
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,a);page.get_by_test_id('tab-results').click();page.get_by_test_id('overall').click()
                heights=[]
                for key in q:
                    expect(page.get_by_test_id('score-'+key)).to_have_text(f'{report["overall"][key]:.2f}');height=page.get_by_test_id('bar-'+key).bounding_box()['height'];heights.append((height,report['overall'][key]))
                scale=heights[0][0]/heights[0][1];assert scale>0 and all(abs(height-value*scale)<2 for height,value in heights)
                page.get_by_test_id('latest').click();expect(page.get_by_test_id('score-'+q[0])).to_have_text('10.00')
                page.get_by_test_id('logout').click();login_page(page,a,'user-b');page.get_by_test_id('tab-results').click();expect(page.get_by_test_id('no-results')).to_be_visible();expect(page.get_by_test_id('bar-'+q[0])).to_have_count(0)
            finally:browser.close()

def ru005():
    with App(PROJECT) as a:
        one=a.login();other=a.login();two=a.login('user-b')
        a.request('/login',{'login':'user-a','password':'wrong'},status=401);a.request('/me',token='invalid',status=401)
        assert a.request('/me',token=one)=={'id':'user-a'}
        a.request('/logout',{},one);a.request('/me',token=one,status=401);assert a.request('/me',token=other)=={'id':'user-a'}
        a.stop();a.start();a.request('/me',token=one,status=401);assert a.request('/me',token=two)=={'id':'user-b'}
        a.request('/goals',{'id':'only-a','title':'Private old goal'},other)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,a);page.get_by_test_id('tab-survey').click();page.get_by_test_id('answer-q1').fill('9')
                page.get_by_test_id('tab-subscription').click();page.get_by_test_id('transaction').fill('old-private-input')
                delayed=[];page.route('**/logout',lambda route:delayed.append(route));page.get_by_test_id('logout').click();wait_pending(page,delayed,1);expect(page.get_by_test_id('signin')).to_be_visible()
                # Start a new user before the old logout response finishes.
                page.get_by_test_id('login').fill('user-b');page.get_by_test_id('password').fill('fixture-only');page.get_by_test_id('signin').click();page.get_by_test_id('tab-survey').click();expect(page.get_by_test_id('answer-q1')).to_have_value('')
                delayed[0].fulfill(response=delayed[0].fetch());page.get_by_test_id('tab-subscription').click();expect(page.get_by_test_id('transaction')).to_have_value('')
                page.unroute('**/logout');page.get_by_test_id('logout').click();login_page(page,a)
                pending=[];page.route('**/goals',lambda route:pending.append(route) if route.request.method=='GET' else route.continue_())
                page.get_by_test_id('tab-goals').click();page.get_by_test_id('goal-title').fill('New old-user goal');page.get_by_test_id('add-goal').click();wait_pending(page,pending,1)
                saved=pending[0].fetch();page.get_by_test_id('logout').click();page.get_by_test_id('login').fill('user-b');page.get_by_test_id('password').fill('fixture-only');page.get_by_test_id('signin').click();wait_pending(page,pending,2)
                pending[1].fulfill(response=pending[1].fetch());page.get_by_test_id('tab-goals').click();pending[0].fulfill(response=saved);page.wait_for_timeout(250)
                expect(page.get_by_text('Private old goal',exact=True)).to_have_count(0);expect(page.get_by_text('New old-user goal',exact=True)).to_have_count(0);expect(page.get_by_test_id('goal-title')).to_have_value('')
            finally:browser.close()

def main():
    rows=[]
    for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
        try:test();passed=True;detail='passed'
        except (AssertionError,BrowserTimeout) as error:passed=False;detail=traceback.format_exc()[-6000:]
        rows.append({'ru_id':f'RU-{i:03d}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}

if __name__=='__main__':
    try:print(json.dumps(main()))
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[type(error).__name__+': '+str(error)],'traceback':traceback.format_exc()}));raise SystemExit(2)
