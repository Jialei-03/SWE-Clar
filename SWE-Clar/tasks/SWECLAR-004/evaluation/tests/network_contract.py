"""Independent observed HTTP/browser contracts; no reference implementation import."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import copy
import json
import math
import sys
import traceback
from pathlib import Path
sys.path.insert(0,'/public_tests')
from network_support import App,login_page,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout


def fixture():
    accounts=[]
    for i in range(1,9):
        accounts.append({'id':f'u{i}','display':f'Person {i}','role':'user','password':f'local-check-{i}',
            'x':i-1,'y':0,'interests':['craft','music'] if i%2 else ['craft']})
    for i in range(1,4):
        accounts.append({'id':f'b{i}','display':f'Shop {i}','role':'business','password':f'local-shop-{i}',
            'x':1.00009 if i==1 else 1.00001,'y':0,'interests':['craft']})
    accounts[2].update(x=3,y=4);accounts[3].update(x=0,y=0,interests=[])
    receipts=[{'id':f'issued-{u["id"]}-{plan}-{j}','user_id':u['id'],'plan':plan}
        for u in accounts for j,plan in enumerate(['free','plus','local','regional','global','PLUS','other'])]
    return {'accounts':accounts,'connections':[[f'u{i}',f'u{i+1}'] for i in range(1,8)],'receipts':receipts}


def receipt(f,user,plan):return next(r['id'] for r in f['receipts'] if r['user_id']==user and r['plan']==plan)
def dashboard(app,token):return app.request('/api/dashboard',token=token)
def err(app,path,data,token,status=403,method=None):
    result=app.request(path,data,token,status=status,method=method)
    assert result['error']['code']=={400:'invalid',401:'unauthorized',403:'denied',404:'not_found'}[status]


def check_1():
    f=fixture()
    # Rename a fixture account and its receipts/edges to detect fixed bundled users.
    f['accounts'][0]['id']='actor-x'
    f['accounts'][0]['password']='separate-fixture-password'
    for pair in f['connections']:
        for n,v in enumerate(pair):
            if v=='u1':pair[n]='actor-x'
    for r in f['receipts']:
        if r['user_id']=='u1':r['user_id']='actor-x'
    with App(fixtures=f) as app:
        err(app,'/api/me',None,'',401)
        err(app,'/api/login',{'id':'actor-x','password':'wrong'},'',401)
        a=app.login('actor-x');b=app.login('actor-x');other=app.login('u2');assert a!=b
        user=app.request('/api/me',token=a)['user'];assert user['id']=='actor-x' and user['plan']=='free'
        for value in [user,app.request('/api/people',token=a),app.request('/api/matches',token=a)]:
            serialized=json.dumps(value)
            assert 'password' not in serialized and a not in serialized and b not in serialized
            assert all(x['password'] not in serialized for x in f['accounts'])
        for path in ['/app.py','/storage.py','/fixtures/demo.json','/network.sqlite','/../fixtures/demo.json']:
            app.request(path,token=a,status=404)
        changed={'interests':['books'],'x':-5.25,'y':6}
        app.request('/api/profile',changed,a,method='PUT')
        assert app.request('/api/me',token=other)['user']['interests']==f['accounts'][1]['interests']
        original=app.request('/api/me',token=a)
        app.stop();app.start();assert app.request('/api/me',token=a)==original
        assert app.database_probe()['integrity']=='ok' and app.database_probe()['tables']>0
        app.request('/api/logout',{},a);err(app,'/api/me',None,a,401)
        assert app.request('/api/me',token=b)==original
        err(app,'/api/profile',{**changed,'id':'u2'},b,400,'PUT')
        assert app.request('/api/me',token=b)==original


def check_2():
    with App(fixtures=fixture()) as app:
        token=app.login();base=app.request('/api/me',token=token)
        invalid=[{'interests':['craft','craft'],'x':0,'y':0},{'interests':['Upper'],'x':0,'y':0},
            {'interests':['a']*11,'x':0,'y':0},{'interests':[],'x':True,'y':0},
            {'interests':[],'x':1000.01,'y':0},{'interests':[],'x':0,'y':float('nan')},
            {'interests':'craft','x':0,'y':0},{'interests':[''],'x':0,'y':0},
            {'interests':[3],'x':0,'y':0},{'interests':[],'x':0},
            {'interests':[],'x':0,'y':0,'user_id':'u2'}]
        for body in invalid:
            err(app,'/api/profile',body,token,400,'PUT');assert app.request('/api/me',token=token)==base
        for q in ['radius=-1','radius=3001','radius=nan','radius=inf','radius=x','role=admin','role=','radius=1&radius=2','wat=1']:
            err(app,'/api/matches?'+q,None,token,400)
        app.request('/api/profile',{'interests':[],'x':-1000,'y':1000},token,method='PUT')
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,app)
                for width in [375,1280]:
                    page.set_viewport_size({'width':width,'height':1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    for selector in ['#profile button','#discover button','#message-form button','#group-form button','#post-form button','#subscribe button']:
                        expect(page.locator(selector)).to_be_visible()
                page.locator('#interests').fill('craft,music');page.locator('#x').fill('0');page.locator('#y').fill('0');page.locator('#profile button').click();expect(page.locator('#feedback')).to_have_text('saved')
                assert app.request('/api/me',token=token)['user']['interests']==['craft','music']
                page.locator('#discover button').click();page.locator('#results [data-user-id]').first.wait_for()
                actual=page.locator('#results [data-user-id]').evaluate_all('(xs)=>xs.map(x=>x.dataset.userId)')
                assert actual==[r['id'] for r in app.request('/api/matches?radius=10&role=all',token=token)['matches']]
                page.locator('#target').select_option('u2');page.locator('#message').fill('   ');page.locator('#message-form button').click();expect(page.locator('#feedback')).to_have_text('invalid');expect(page.locator('#message')).to_have_value('   ')
                literal='<img src=x onerror="window.textExecuted=1"> & hello'
                page.locator('#message').fill(literal);page.locator('#message-form button').click();expect(page.locator('#message')).to_have_value('');expect(page.locator('#messages')).to_contain_text(literal);assert page.evaluate('window.textExecuted') is None
                assert dashboard(app,token)['messages'][-1]['content']==literal
                page.locator('#group-name').fill('Browser group');page.locator('#group-form button').click();page.locator('#group-select option').first.wait_for(state='attached')
                page.locator('#content').fill('   ');page.locator('#post-form button').click();expect(page.locator('#feedback')).to_have_text('invalid');expect(page.locator('#content')).to_have_value('   ')
                page.locator('#content').fill(literal);page.locator('#post-form button').click();expect(page.locator('#content')).to_have_value('');expect(page.locator('#posts')).to_contain_text(literal);assert page.evaluate('window.textExecuted') is None
                page.locator('#posts button').click();expect(page.locator('#posts')).to_contain_text('Likes: 1')
                page.locator('#logout').click();expect(page.locator('#login')).to_be_visible()
                for selector in ['#messages','#posts','#results']:expect(page.locator(selector)).to_be_empty()
                page.locator('#username').fill('u8');page.locator('#password').fill('local-check-8');page.locator('#login button').click();expect(page.locator('#identity')).to_contain_text('u8');expect(page.locator('#messages')).to_be_empty();expect(page.locator('#posts')).to_be_empty()
            finally:browser.close()


def expected_matches(f,actor,radius,role='all',blocks=()):
    # Independent all-pairs relaxation, rather than importing candidate traversal.
    users={u['id']:u for u in f['accounts']};ids=sorted(users);ban={frozenset(x) for x in blocks}
    steps={(a,b):0 if a==b else 100 for a in ids for b in ids}
    for a,b in f['connections']:
        if frozenset((a,b)) not in ban:steps[a,b]=steps[b,a]=1
    for k in ids:
        for a in ids:
            for b in ids:steps[a,b]=min(steps[a,b],steps[a,k]+steps[k,b])
    me=users[actor];rows=[]
    for ident,u in users.items():
        dist=((u['x']-me['x'])**2+(u['y']-me['y'])**2)**0.5
        if ident==actor or frozenset((actor,ident)) in ban or dist>radius or (role!='all' and role!=u['role']):continue
        rows.append({'id':ident,'display':u['display'],'role':u['role'],'distance':dist,'shared':len(set(me['interests']).intersection(u['interests'])),'degree':min(steps[actor,ident],7)})
    return sorted(rows,key=lambda r:(-r['shared'],r['degree'],r['distance'],r['id']))


def assert_matches(app,token,f,radius,role='all',blocks=()):
    want=expected_matches(f,'u1',radius,role,blocks);got=app.request(f'/api/matches?radius={radius}&role={role}',token=token)['matches']
    assert [r['id'] for r in got]==[r['id'] for r in want],(got,want)
    for row,exp in zip(got,want):
        assert all(row[k]==v for k,v in exp.items() if k!='distance')
        assert type(row['degree']) is int and type(row['shared']) is int
        assert math.isclose(row['distance'],exp['distance'],rel_tol=1e-12,abs_tol=1e-12)


def check_3():
    f=fixture()
    with App(fixtures=f) as app:
        t={u['id']:app.login(u['id']) for u in f['accounts']}
        for radius in [0,1.00001,1.00009,5,6,3000]:assert_matches(app,t['u1'],f,radius)
        for role in ['user','business']:assert_matches(app,t['u1'],f,3000,role)
        app.request('/api/connection',{'target':'b1','decision':'request'},t['u1']);assert_matches(app,t['u1'],f,3000)
        app.request('/api/connection',{'target':'u1','decision':'accept'},t['b1']);f['connections'].append(['u1','b1']);assert_matches(app,t['u1'],f,3000)
        app.request('/api/block',{'target':'u3','blocked':True},t['u4']);assert_matches(app,t['u1'],f,3000,blocks=[('u4','u3')])
        app.request('/api/block',{'target':'u1','blocked':True},t['b2']);assert_matches(app,t['u1'],f,3000,blocks=[('u4','u3'),('b2','u1')])
        app.request('/api/block',{'target':'u3','blocked':False},t['u4']);app.request('/api/block',{'target':'u1','blocked':False},t['b2']);assert_matches(app,t['u1'],f,3000)
        profile={'interests':['music'],'x':3,'y':4};app.request('/api/profile',profile,t['u1'],method='PUT');f['accounts'][0].update(profile);assert_matches(app,t['u1'],f,5)


def check_4():
    f=fixture();f['connections']=[]
    with App(fixtures=f) as app:
        t={u['id']:app.login(u['id']) for u in f['accounts']}
        a,b,c=t['u1'],t['u2'],t['u3']
        for token,target in [(a,'u2'),(b,'u1')]:err(app,'/api/message',{'target':target,'content':'No connection'},token)
        err(app,'/api/connection',{'target':'u2','decision':'accept'},a)
        assert not app.request('/api/connection',{'target':'u2','decision':'request'},a)['accepted']
        assert not app.request('/api/connection',{'target':'u1','decision':'request'},b)['accepted']
        err(app,'/api/connection',{'target':'u2','decision':'accept'},a)
        for _ in range(2):assert app.request('/api/connection',{'target':'u1','decision':'accept'},b)['accepted']
        assert len(dashboard(app,a)['connections'])==1
        ids=[app.request('/api/message',{'target':'u2','content':'  Independent message  '},a)['id'] for _ in range(2)];assert len(set(ids))==2
        messages=dashboard(app,b)['messages'];assert len(messages)==2 and all(m['sender']=='u1' and m['recipient']=='u2' and m['content']=='Independent message' for m in messages)
        assert dashboard(app,c)['messages']==[]
        err(app,'/api/message',{'target':'u2','content':'Forged','sender':'u3'},a,400)
        group=app.request('/api/group',{'name':'  Makers  '},a)['id'];assert dashboard(app,a)['groups'][0]['name']=='Makers'
        before=dashboard(app,a)
        err(app,'/api/invite',{'group_id':group,'target':'u3'},b)
        err(app,'/api/post',{'group_id':group,'content':'Outsider','featured':False},b)
        assert dashboard(app,a)==before and dashboard(app,b)['groups']==[]
        for _ in range(2):app.request('/api/invite',{'group_id':group,'target':'u2'},a)
        assert len(dashboard(app,b)['groups'])==1
        app.request('/api/invite',{'group_id':group,'target':'u3'},a)
        posts=[app.request('/api/post',{'group_id':group,'content':'  Workshop post  ','featured':False},b)['id'] for _ in range(2)];assert len(set(posts))==2
        outsider=t['b1'];err(app,'/api/like',{'post_id':posts[0]},outsider)
        for _ in range(2):assert app.request('/api/like',{'post_id':posts[0]},a)['likes']==1
        assert app.request('/api/like',{'post_id':posts[0]},b)['likes']==2
        app.request('/api/block',{'target':'u2','blocked':True},c)
        err(app,'/api/like',{'post_id':posts[0]},c);assert dashboard(app,c)['posts']==[]
        app.request('/api/block',{'target':'u2','blocked':False},c)
        app.request('/api/block',{'target':'u1','blocked':True},b)
        for token,target in [(a,'u2'),(b,'u1')]:
            err(app,'/api/message',{'target':target,'content':'Blocked'},token)
            for decision in ['request','accept']:err(app,'/api/connection',{'target':target,'decision':decision},token)
        err(app,'/api/invite',{'group_id':group,'target':'u2'},a)
        err(app,'/api/post',{'group_id':group,'content':'Blocked owner','featured':False},b)
        err(app,'/api/like',{'post_id':posts[0]},a)
        assert dashboard(app,a)['messages']==dashboard(app,b)['messages']==[]
        assert dashboard(app,a)['posts']==[] and dashboard(app,b)['groups']==[]
        app.request('/api/block',{'target':'u1','blocked':False},b)
        assert len(dashboard(app,a)['messages'])==2 and len(dashboard(app,a)['posts'])==2
        assert dashboard(app,a)['posts'][0]['likes']==2
        snapshots={k:dashboard(app,t[k]) for k in ['u1','u2','u3']}
        app.stop();app.start()
        assert all(dashboard(app,t[k])==v for k,v in snapshots.items())


def check_5():
    f=fixture()
    with App(fixtures=f) as app:
        u=app.login();b=app.login('b1');other=app.login('b2')
        gu=app.request('/api/group',{'name':'Personal group'},u)['id'];gb=app.request('/api/group',{'name':'Business group'},b)['id']
        def redeem(token,user,plan):return app.request('/api/subscribe',{'receipt_id':receipt(f,user,plan)},token)['plan']
        for token,user,wrong in [(u,'u1','local'),(b,'b1','plus'),(u,'u1','PLUS'),(b,'b1','other')]:
            err(app,'/api/subscribe',{'receipt_id':receipt(f,user,wrong)},token);assert app.request('/api/me',token=token)['user']['plan']=='free'
        err(app,'/api/subscribe',{'receipt_id':'not-issued'},b)
        err(app,'/api/subscribe',{'receipt_id':receipt(f,'b1','local')},other)
        err(app,'/api/subscribe',{'receipt_id':receipt(f,'b1','local'),'plan':'global'},b,400)
        assert app.request('/api/me',token=other)['user']['plan']=='free'
        for token,group in [(u,gu),(b,gb)]:err(app,'/api/post',{'group_id':group,'content':'Unpaid feature','featured':True},token)
        assert redeem(u,'u1','plus')=='plus';err(app,'/api/post',{'group_id':gu,'content':'Personal feature','featured':True},u)
        for plan in ['local','regional','global']:
            assert redeem(b,'b1',plan)==plan
            app.request('/api/post',{'group_id':gb,'content':plan,'featured':True},b)
        assert redeem(b,'b1','free')=='free'
        assert redeem(b,'b1','local')=='free'
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(lambda _:redeem(other,'b2','regional'),range(8)))
        assert results==['regional']*8
        assert redeem(other,'b2','free')=='free'
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            assert list(executor.map(lambda _:redeem(other,'b2','regional'),range(8)))==['free']*8
        old=dashboard(app,b)['posts'];assert len(old)==3 and all(p['featured'] for p in old)
        err(app,'/api/post',{'group_id':gb,'content':'Downgraded','featured':True},b)
        app.request('/api/post',{'group_id':gb,'content':'Ordinary','featured':False},b)
        app.stop();app.start();assert redeem(b,'b1','global')=='free';assert dashboard(app,b)['posts'][:3]==old
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();login_page(page,app,'b3')
                page.locator('#receipt').fill(receipt(f,'b3','local'));page.locator('#subscribe button').click();expect(page.locator('#plan')).to_have_text('local')
                page.locator('#group-name').fill('Page membership');page.locator('#group-form button').click();page.locator('#group-select option').first.wait_for(state='attached')
                page.locator('#featured').check();page.locator('#content').fill('Browser featured');page.locator('#post-form button').click();expect(page.locator('#posts')).to_contain_text('Featured');expect(page.locator('#posts')).to_contain_text('Browser featured')
                page.locator('#receipt').fill(receipt(f,'b3','free'));page.locator('#subscribe button').click();expect(page.locator('#plan')).to_have_text('free')
                page.locator('#content').fill('Must remain');page.locator('#post-form button').click();expect(page.locator('#feedback')).to_have_text('denied');expect(page.locator('#content')).to_have_value('Must remain')
                expect(page.locator('#posts')).not_to_contain_text('Must remain')
            finally:browser.close()


def main():
    results=[];infra=[]
    for i,test in enumerate([check_1,check_2,check_3,check_4,check_5],1):
        try:test();result={'ru_id':f'RU-{i:03d}','passed':True}
        except (AssertionError,BrowserTimeout) as e:
            traceback.print_exc(file=sys.stderr);result={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(e)[-2000:]}
        except Exception as e:
            traceback.print_exc(file=sys.stderr);infra.append(f'RU-{i:03d}: {type(e).__name__}: {e}');result={'ru_id':f'RU-{i:03d}','passed':False,'detail':'Unattributed evaluator error'}
        results.append(result)
    print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}));return 2 if infra else 0


if __name__=='__main__':raise SystemExit(main())
