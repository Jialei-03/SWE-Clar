"""Private observable-behavior gates. The candidate is always a separate process."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
from copy import deepcopy
import json
import re
from contextlib import contextmanager
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.parse import quote
sys.path.insert(0,'/public_tests')
from listing_support import Workspace,event,draft,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout


def number_pattern(value):
    """A whole numeric value, with optional conventional digit grouping."""
    digits=str(value)
    groups=[]
    while digits:
        groups.insert(0,digits[-3:]);digits=digits[:-3]
    grouped=r"[,\u00a0\u202f '’]".join(groups)
    return re.compile(r'(?<![\d.])(?<!\d[.,])(?:'+str(value)+'|'+grouped+r')(?:\.0+)?(?!\d|[.,]\d)')


@contextmanager
def poll_response(peer, payload):
    """Override only the test-owned server's polling response over real HTTP."""
    handler=peer.server.RequestHandlerClass
    original=handler.do_GET
    def get(request):
        if request.path.startswith('/offers?'):
            peer.requests.append({'method':'GET','path':request.path})
            return request.send(200,payload)
        return original(request)
    handler.do_GET=get
    try:yield
    finally:handler.do_GET=original


def ru1():
    with Workspace() as work:
        saved=work.request('/api/listings',draft(),status=201)['listing']
        work.restart();assert work.request('/api/listings/'+saved['id'])['listing']==saved
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(work.app.url)
                page.locator('#listings [data-id="parcel-a"]').click()
                expect(page.locator('#draft-form [name="label"]')).to_have_value('Synthetic Parcel A')
                page.locator('#draft-form [name="label"]').fill('Synthetic public browser parcel')
                page.locator('#draft-form button').click()
                expect(page.locator('#title')).to_have_text('Synthetic public browser parcel')
            finally:browser.close()


def ru2():
    with Workspace() as w:
        original=w.request('/api/listings/parcel-a')['listing']
        invalid=[{'label':'  '},{'label':'a'*121},{'property_type':'castle'},{'bedrooms':True},{'bathrooms':0},{'floor_area':2001},{'asking_price':0},{'features':['']},{'features':[None]},{'features':'garden'},{'features':['x']*21},{'owner_id':'seller-b'},{'state':'published'},{'unknown':1}]
        for fields in invalid:
            w.request('/api/listings/parcel-a',{**fields},method='PUT',status=400)
            assert w.request('/api/listings/parcel-a')['listing']==original
            before=w.request('/api/listings')
            w.request('/api/listings',draft(**fields),status=400)
            assert w.request('/api/listings')==before
        for field in ['label','property_type','bedrooms','bathrooms','floor_area','asking_price']:
            body=draft();del body[field];response=w.request('/api/listings',body,status=400);assert field in response['errors']
        saved=w.request('/api/listings/parcel-a',{'label':'  Trimmed parcel  ','features':['shed',' garden ','shed']},method='PUT')['listing']
        assert saved['features']==['shed','garden'] and saved['label']=='Trimmed parcel'
        assert saved['asking_price']==original['asking_price'] and saved['state']=='draft'
        w.restart();assert w.request('/api/listings/parcel-a')['listing']==saved


def comparable(key,price=200000,**values):
    return {'id':key,'property_type':'house','bedrooms':3,'floor_area':100,'sale_price':price,'age_days':1,**values}


def analyze(w,comps,**values):
    return w.request('/api/listings/parcel-a/analysis',{'comparables':comps,'count':2,'tone':'warm',**values})


def ru3():
    with Workspace() as w:
        comps=[comparable('age',200000,age_days=180),comparable('area-low',150000,floor_area=75),comparable('area-high',300000,floor_area=125),comparable('beds',220000,bedrooms=4),comparable('type',1,property_type='apartment'),comparable('old',1,age_days=181),comparable('small',1,floor_area=74),comparable('large',1,floor_area=126),comparable('beds-out',1,bedrooms=5),comparable('invalid',True),comparable('invalid-age',1,age_days=False)]
        result=analyze(w,comps)['pricing']
        assert result=={'minimum':200000,'midpoint':210000,'maximum':240000,'confidence':0.8,'comparable_ids':['area-high','area-low','beds','age'],'adjusted_prices':[240000,200000,220000,200000]}
        selected=[comparable('z'+str(i),100000+i*10000,age_days=9-i) for i in range(9)]
        result=analyze(w,selected)['pricing'];assert result['comparable_ids']==['z8','z7','z6','z5','z4'];assert result['midpoint']==160000 and result['confidence']==1
        # Structural validity precedes duplicate-ID replacement, then eligibility filtering.
        dup=[comparable('duplicate',100000),comparable('duplicate',300000),comparable('duplicate',False),comparable('other',200000)]
        result=analyze(w,dup)['pricing'];assert result['comparable_ids']==['duplicate','other'] and result['midpoint']==250000
        assert analyze(w,[comparable('x'),comparable('x',1,age_days=181)])['pricing'] is None
        assert analyze(w,[None,{},comparable('bad',0)])['pricing'] is None
        # Half-up once at the final arithmetic result, not a binary-float/bankers rounding.
        result=analyze(w,[comparable('a',100000),comparable('b',100001)])['pricing'];assert result['midpoint']==100001
        result=analyze(w,[comparable('a',999,floor_area=120),comparable('b',1000,floor_area=120)])['pricing'];assert result['midpoint']==833 and result['adjusted_prices']==[833,833]
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(w.app.url);page.locator('#listings [data-id="parcel-a"]').click();page.locator('#comparables').fill(json.dumps([comparable('single',235001)]));page.locator('#analyze').click();expect(page.locator('#analysis')).to_contain_text(number_pattern(235001))
            finally:browser.close()


def ru4():
    with Workspace() as w:
        for fields in [draft(label='Synthetic Amber',features=['courtyard','green door']),draft(label='Synthetic Indigo',property_type='apartment',bedrooms=1,bathrooms=1,floor_area=52,asking_price=170123,features=['balcony'])]:
            saved=w.request('/api/listings',fields,status=201)['listing']
            for count in [2,3]:
                for tone in ['warm','concise']:
                    body={'comparables':[comparable('unrelated',100000,features=['swimming pool'])],'count':count,'tone':tone}
                    first=w.request('/api/listings/'+saved['id']+'/analysis',body)['descriptions'];second=w.request('/api/listings/'+saved['id']+'/analysis',body)['descriptions']
                    assert first==second and len(first)==count and len(set(first))==count
                    for text in first:
                        assert isinstance(text,str) and not text.lstrip().startswith(('{','['))
                        for value in [fields['label'],fields['property_type'],tone,*fields['features']]:assert value in text
                        for key in ['bedrooms','bathrooms','floor_area','asking_price']:assert number_pattern(fields[key]).search(text), (key,text)
                        assert not any(x in text.lower() for x in ['swimming pool','guaranteed return','top school','investment guarantee'])
        for values in [{'count':1},{'count':True},{'tone':'invented'},{'comparables':None}]:
            w.request('/api/listings/parcel-a/analysis',{'comparables':[],'count':2,'tone':'warm',**values},status=400)


def ru5():
    # Each malformed 200 must leave both data and checkpoints untouched.
    malformed=[{'events':[],'cursor':0}, {'events':[event(2)],'cursor':1},
               {'events':[event(3),event(2)],'cursor':3},
               {'events':[event(2),event(2)],'cursor':2},
               {'events':[event(1)],'cursor':2},
               {'events':[event(2),event(3,amount=True)],'cursor':3},
               {'events':[event(2),event(3,listing_id='missing')],'cursor':3},
               {'events':None,'cursor':2}, {'events':[],'cursor':True}]
    for payload in malformed:
        with Workspace([event()]) as w:
            w.request('/api/sync',{'now':0})
            before=w.request('/api/listings/parcel-a')
            with poll_response(w.peer,payload):
                w.request('/api/sync',{'now':120},status=502)
            assert w.request('/api/listings/parcel-a')==before
            w.restart();w.peer.extend([event(2)])
            assert w.request('/api/sync',{'now':120})=={'mode':'poll','updated':1,'polled':True}
            assert w.peer.requests[-1]['path']=='/offers?after=1'
            assert len(w.request('/api/listings/parcel-a')['notifications'])==2
    with Workspace([event()]) as w:
        assert w.request('/api/sync',{'now':0})=={'mode':'poll','updated':1,'polled':True}
        initial=len(w.peer.requests);assert w.request('/api/sync',{'now':119})['polled'] is False;assert len(w.peer.requests)==initial
        w.peer.extend([event(2),event(3)])
        assert w.request('/api/sync',{'now':120})['updated']==2
        snapshot=w.request('/api/listings/parcel-a');assert snapshot['offers'][0]['revision']==3 and len(snapshot['notifications'])==3
        assert [n['revision'] for n in snapshot['notifications']]==[1,2,3]
        assert all(n['actor']=='seller-a' for n in snapshot['notifications'])
        assert snapshot['notifications'][-1]['data']=={'amount':190003,'terms':'Synthetic terms'}
        assert w.request('/api/offer-events',{'events':[event(2)]})['updated']==0
        assert w.request('/api/listings/parcel-a')==snapshot
        w.peer.extend([event(4)]);w.peer.fail_reads=True;w.request('/api/sync',{'now':240},status=502)
        assert w.request('/api/listings/parcel-a')==snapshot
        w.peer.fail_reads=False;assert w.request('/api/sync',{'now':240})['updated']==1
        assert w.peer.requests[-1]['path']=='/offers?after=3'
        for invalid in [event(6,listing_id='missing'),event(6,amount=True),{**event(6),'revision':0},event(6,terms=''),event(6,external_id='offer-a',listing_id='parcel-b')]:
            before=w.request('/api/listings/parcel-a');w.request('/api/offer-events',{'events':[event(5),invalid]},status=400);assert w.request('/api/listings/parcel-a')==before
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:w.request('/api/offer-events',{'events':[event(5)]}),range(8)))
        assert sum(r['updated'] for r in replies)==1
        before=w.request('/api/listings/parcel-a');w.restart();assert w.request('/api/listings/parcel-a')==before
        initial=len(w.peer.requests);assert w.request('/api/sync',{'now':359})['polled'] is False;assert len(w.peer.requests)==initial
    with Workspace([event()],webhooks=True) as w:
        assert w.request('/api/sync',{'now':0})=={'mode':'webhook','updated':0,'polled':False}
        before=len(w.peer.requests);w.request('/api/sync',{'now':10000});assert len(w.peer.requests)==before
        assert w.peer.push([event()])==[{'status':200,'body':{'updated':1}}]
        assert w.peer.push([event()])==[{'status':200,'body':{'updated':0}}]
        assert not any(r['path'].startswith('/offers?') for r in w.peer.requests)
        w.restart();w.request('/api/sync',{'now':10001});assert w.peer.subscriptions==[w.app.url+'/api/offer-events']
        assert w.peer.push([event(2)])==[{'status':200,'body':{'updated':1}}]


def ru6():
    with Workspace() as w:
        w.request('/api/offer-events',{'events':[event(),event(external_id='offer-b',listing_id='parcel-b')]})
        for actor,ids in [('seller-a',['parcel-a']),('seller-b',['parcel-b']),('agent-a',['parcel-a']),('agent-b',['parcel-b']),('admin',['parcel-a','parcel-b'])]:
            assert [r['id'] for r in w.request('/api/listings',actor=actor)['listings']]==ids
            if 'parcel-a' not in ids:
                w.request('/api/listings/parcel-a',actor=actor,status=404);w.request('/api/listings/parcel-a',{'label':'Unauthorized'},actor=actor,method='PUT',status=404);w.request('/api/listings/parcel-a/analysis',{'comparables':[],'count':2,'tone':'warm'},actor=actor,status=404);w.request('/api/offers/offer-a/review',{},actor=actor,status=404)
        w.request('/api/listings',draft(),actor='agent-a',status=403);w.request('/api/listings',draft(),actor='admin',status=403)
        w.request('/api/listings/parcel-a',{'label':'Updated by assigned agent'},actor='agent-a',method='PUT')
        w.request('/api/listings/parcel-a',{'label':'Admin edit'},actor='admin',method='PUT',status=403)
        w.request('/api/listings',actor='unknown',status=401)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(w.app.url);page.locator('#listings [data-id="parcel-a"]').click();expect(page.locator('#offers')).to_contain_text('Synthetic terms')
                page.locator('#actor').select_option('seller-b');expect(page.locator('#listings [data-id="parcel-b"]')).to_be_visible();expect(page.locator('#listings [data-id="parcel-a"]')).to_have_count(0);expect(page.locator('#offers')).to_be_empty();expect(page.locator('#notifications')).to_be_empty()
            finally:browser.close()


def assert_review_notice(before,after,offer,actor='seller-a'):
    """Identify a review by its operation delta, not an undocumented kind token."""
    prior={n['sequence'] for n in before['notifications']}
    added=[n for n in after['notifications'] if n['sequence'] not in prior]
    assert len(added)==1, 'Review must create exactly one new notice'
    notice=added[0]
    assert isinstance(notice['kind'],str) and notice['kind']
    assert notice['offer_id']==offer['external_id'] and notice['actor']==actor
    assert notice['revision']==offer['revision'] and notice['listing_id']==offer['listing_id']
    assert notice['data']=={'amount':offer['amount'],'terms':offer['terms']}


def ru7():
    with Workspace() as w:
        special='offer/one?x=#part';e=event(external_id=special)
        w.peer.extend([e]);w.request('/api/offer-events',{'events':[e]})
        path='/api/offers/'+quote(special,safe='')+'/review'
        before=w.request('/api/listings/parcel-a');original=before['offers']
        first=w.request(path,{});assert first['url']==w.peer.url+'/review/'+quote(special,safe='')
        with urlopen(first['url'],timeout=3) as response:assert b'Synthetic terms' in response.read()
        reviewed=w.request('/api/listings/parcel-a');assert_review_notice(before,reviewed,e)
        w.request(path,{});w.restart();w.request(path,{})
        detail=w.request('/api/listings/parcel-a');assert detail['offers']==original
        assert detail['notifications']==reviewed['notifications'], 'Repeated review must remain idempotent after restart'
        e=event(2,external_id=special);w.peer.extend([e]);w.request('/api/offer-events',{'events':[e]})
        before=w.request('/api/listings/parcel-a');w.request(path,{})
        assert_review_notice(before,w.request('/api/listings/parcel-a'),e)
        assert all(r['method']=='GET' for r in w.peer.requests)


def main():
    results=[];infrastructure=[]
    for index,fn in enumerate([ru1,ru2,ru3,ru4,ru5,ru6,ru7],1):
        try:fn();results.append({'ru_id':f'RU-{index:03d}','passed':True})
        except (AssertionError,BrowserTimeout) as error:
            results.append({'ru_id':f'RU-{index:03d}','passed':False,'detail':type(error).__name__+': '+str(error)[:800]})
        except Exception as error:
            infrastructure.append({'gate':index,'type':type(error).__name__,'detail':str(error)[:1200]})
    print(json.dumps({'harness_ok':not infrastructure,'results':results,'infrastructure_errors':infrastructure}));return 2 if infrastructure else 0


if __name__=='__main__':raise SystemExit(main())
