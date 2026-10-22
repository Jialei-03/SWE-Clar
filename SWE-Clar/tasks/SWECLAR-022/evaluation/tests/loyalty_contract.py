"""Protected behavioral oracle; never imports candidate modules or schema."""
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
sys.path.insert(0, os.environ.get('CLARSWE_PUBLIC_TESTS', '/public_tests'))
from PIL import Image, PngImagePlugin
from playwright.sync_api import expect
from loyalty_support import Application, browser_session, request


class Checks:
    def __init__(self): self.count = 0
    def require(self, condition, detail):
        if not condition: raise AssertionError(detail)
        self.count += 1


class Session:
    def __init__(self, app, checks): self.app, self.checks, self.tokens = app, checks, {}
    def token(self, who):
        if who not in self.tokens:
            user = next(u for u in self.app.seed['users'] if u['id'] == who)
            response = request(self.app, '/api/login', {'username': user['username'], 'password': user['password']})
            self.checks.require(response['status'] == 200, 'Valid synthetic login')
            self.tokens[who] = response['body']['token']
        return self.tokens[who]
    def api(self, path, who='consumer-a', body=None, method=None, status=200, code=None, raw=False):
        response = request(self.app, path, body, token=self.token(who), method=method, raw=raw)
        self.checks.require(response['status'] == status, f'{method or ("GET" if body is None else "POST")} {path}: expected {status}, got {response["status"]}')
        if code: self.checks.require(response['body'].get('error', {}).get('code') == code, 'Expected error ' + code)
        return response['body']
    def restart(self): self.app.stop(); self.app.start(); self.tokens = {}
    def photo(self, who='consumer-a', pixel=(51,103,201,117)):
        image = Image.new('RGBA', (11,7), pixel); output = BytesIO(); metadata = PngImagePlugin.PngInfo(); metadata.add_text('Comment','Synthetic metadata')
        image.save(output,format='PNG',pnginfo=metadata)
        asset = self.api('/api/assets',who,{'png_base64':base64.b64encode(output.getvalue()).decode()},status=201)['asset']
        return asset,image.tobytes()
    def receipt(self, key='r1', who='consumer-a', amount=750, **overrides):
        asset,_=self.photo(who)
        payload=dict(request_id=key,branch_id='branch-a',receipt_number=key,date='2024-02-29',amount_cents=amount,asset_id=asset['id']);payload.update(overrides)
        return self.api('/api/receipts',who,payload,status=201)['receipt'],payload
    def review(self,row,decision='approved',**kwargs):
        return self.api('/api/receipts/'+quote(row['id'],safe='')+'/review','admin',{'decision':decision},**kwargs)
    def preferences(self,who='consumer-a',categories=None,malls=None):
        return self.api('/api/preferences',who,{'categories':['food'] if categories is None else categories,'mall_ids':['mall-a'] if malls is None else malls},method='PUT')['preferences']
    def promotion(self,title='Promotion',**overrides):
        who=overrides.pop('who','merchant-a')
        payload=dict(shop_id='shop-a',branch_ids=['branch-a'],title=title,body='Synthetic literal <b>message</b>',due_at=500,expires_at=1200);payload.update(overrides)
        return self.api('/api/promotions',who,payload,status=201)['promotion']
    def dispatch(self,**kwargs): return self.api('/api/dispatch','admin',{},**kwargs)['delivered_count']
    def inbox(self,who='consumer-a'): return self.api('/api/inbox',who)['messages']


def browser_login(page,app,who):
    user=next(u for u in app.seed['users'] if u['id']==who)
    page.goto(app.url);page.locator('#username').fill(user['username']);page.locator('#password').fill(user['password']);page.locator('#login').click()
    expect(page.locator('#workspace')).to_be_visible()


def directory(c):
    with Application() as app:
        s=Session(app,c)
        c.require(request(app,'/api/catalog')['status']==401,'Catalog requires session')
        for who in ('consumer-a','merchant-a'):
            s.api('/api/malls',who,{'id':'no','name':'No'},status=403,code='forbidden')
            s.api('/api/malls',who,b'{',status=403,code='forbidden')
        c.require(request(app,'/api/malls',b'{')['status']==401,'Authentication before malformed JSON')
        s.api('/api/malls','admin',b'{',status=400,code='invalid_request')
        s.api('/api/malls','admin',{'id':'mall / 雨?','name':'  <script>literal</script>  '},status=201)
        s.api('/api/malls','admin',{'id':'mall / 雨?','name':'second'},status=409,code='duplicate_id')
        s.api('/api/shops','admin',{'id':'new','name':'New','owner_id':'consumer-a','category':'food'},status=422,code='invalid_owner')
        s.api('/api/shops','admin',{'id':'new','name':'New','owner_id':'merchant-new','category':'food'},status=201)
        for identity in ('same-mall-1','same-mall-2'):
            s.api('/api/branches','admin',{'id':identity,'shop_id':'new','mall_id':'mall / 雨?','participating':True},status=201)
        s.api('/api/branches/same-mall-1','admin',{'participating':False,'shop_id':'evil'},method='PATCH')
        catalog=s.api('/api/catalog')
        row=next(r for r in catalog['branches'] if r['id']=='same-mall-1')
        c.require(row['shop_id']=='new' and row['participating'] is False,'Only flag changes')
        old=s.token('consumer-a');s.restart()
        c.require(request(app,'/api/catalog',token=old)['status']==401,'Restart invalidates session')
        c.require(s.api('/api/catalog')==catalog,'Directory survives restart')
        with browser_session() as browser:
            page=browser.new_page(viewport={'width':390,'height':844});browser_login(page,app,'admin')
            expect(page.locator('#catalog')).to_contain_text('<script>literal</script>')
            c.require(page.locator('#catalog script').count()==0,'Literal directory text')
            page.locator('#shop-id').fill('browser-shop');page.locator('#shop-name').fill('Synthetic fresh merchant');page.locator('#shop-owner').select_option('merchant-new');page.locator('#create-shop').click()
            expect(page.locator('[data-shop-id="browser-shop"]')).to_be_visible()
            page.locator('#logout').click();expect(page.locator('#workspace')).to_be_hidden()
            c.require(page.locator('#shop-name').input_value()=='','Logout clears admin drafts')
            browser_login(page,app,'consumer-b')
            expect(page.locator('#create-shop')).to_be_hidden()
            for width,height in [(390,844),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height});c.require(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Responsive page')
            # Construct through the declared class, never require a reference-page instance name.
            page.evaluate("async () => { window.probeClient=new window.LoyaltyClient(); await window.probeClient.login('consumer-a','synthetic-pass'); }")
            for status in (401,200):
                held=[]
                def intercept(route):
                    if not held: held.append(route)
                    else: route.continue_()
                page.route('**/api/catalog',intercept)
                page.evaluate("() => { window.pendingRefresh=window.probeClient.refresh(); }")
                for _ in range(100):
                    if held: break
                    page.wait_for_timeout(20)
                c.require(bool(held),'Old-account request captured')
                page.evaluate("async () => { await window.probeClient.login('admin','synthetic-pass'); }")
                if status==401: body={'error':{'code':'unauthenticated'}}
                else: body={'malls':[{'id':'old-snapshot','name':'Old response'}],'shops':[],'branches':[],'rewards':[]}
                held[0].fulfill(status=status,content_type='application/json',body=json.dumps(body))
                page.evaluate("async () => { try { await window.pendingRefresh; } catch (_) {} }")
                state=page.evaluate("() => ({user:window.probeClient.user,malls:window.probeClient.malls})")
                c.require(state['user']['id']=='admin' and not any(m['id']=='old-snapshot' for m in state['malls']),'Old success/401 cannot overwrite or clear newer account')
                page.unroute('**/api/catalog',intercept)
            page.evaluate("() => window.probeClient.dispose()")



def images(c):
    with Application() as app:
        s=Session(app,c);asset,pixels=s.photo()
        s.api('/api/assets','admin',status=403,code='forbidden')
        s.api(asset['url'],'consumer-b',status=404,raw=True)
        s.api(asset['url'],'admin',status=404,raw=True)
        s.api('/api/assets',body={'png_base64':'not PNG'},status=400,code='invalid_request')
        blob=s.api(asset['url'],raw=True);decoded=Image.open(BytesIO(blob));decoded.load()
        c.require(decoded.size==(11,7) and decoded.convert('RGBA').tobytes()==pixels,'Stored exact PNG pixels')
        c.require(not decoded.info,'Image metadata discarded')
        payload=dict(request_id='visible / 雨',branch_id='branch-a',receipt_number='  Visible  ',date='2024-02-29',amount_cents=999,asset_id=asset['id'])
        s.api('/api/receipts','consumer-b',payload,status=404,code='not_found')
        s.api('/api/receipts',body=dict(payload,date='2023-02-29'),status=400,code='invalid_request')
        s.api('/api/receipts',body=dict(payload,amount_cents=True),status=400,code='invalid_request')
        s.api('/api/receipts',body=dict(payload,branch_id='branch-off'),status=422,code='not_participating')
        receipt=s.api('/api/receipts',body=payload,status=201)['receipt']
        c.require(receipt['status']=='pending' and receipt['points']==0 and receipt['reviewed_by'] is None,'Pending uncredited receipt')
        c.require(receipt['receipt_number']=='Visible' and receipt['amount_cents']==999,'Structured normalized receipt')
        c.require(s.api('/api/wallet')['balance']==0,'Upload and pending submit do not credit')
        c.require(s.api(asset['url'],'admin',raw=True)==blob,'Admin can inspect attached actual image')
        c.require(not s.api('/api/receipts','consumer-b')['receipts'],'Other consumer has no receipt')
        s.api('/api/receipts','merchant-a',status=403,code='forbidden')
        s.restart();c.require(s.api('/api/receipts')['receipts']==[receipt],'Receipt persists')
        c.require(s.api(asset['url'],raw=True)==blob,'PNG persists')
        with browser_session() as browser:
            page=browser.new_page();browser_login(page,app,'admin')
            expect(page.locator('[data-receipt-id]')).to_have_count(1)
            expect(page.locator('[data-asset-id] a')).to_be_visible()
            # Check visible rendered pixels without mandating img versus Canvas.
            container=page.locator('[data-asset-id]');expect(container.locator('img,canvas')).to_have_count(1)
            page.wait_for_function("[...document.querySelectorAll('[data-asset-id] img,[data-asset-id] canvas')].some(n=>n.tagName==='CANVAS'?n.width>0:n.naturalWidth>0)")
            c.require(container.screenshot().startswith(b'\x89PNG'),'Actual image display')
            page.locator('#logout').click();expect(page.locator('[data-asset-id]')).to_have_count(0)


def audience(c):
    with Application() as app:
        s=Session(app,c)
        s.api('/api/preferences','merchant-a',status=403,code='forbidden')
        s.api('/api/preferences',body={'categories':['food','food'],'mall_ids':['mall-a']},method='PUT',status=400,code='invalid_request')
        normalized=s.preferences(categories=['leisure','food'],malls=['mall-b','mall-a'])
        c.require(normalized['categories']==['food','leisure'] and normalized['mall_ids']==['mall-a','mall-b'],'Preference canonical order')
        s.preferences('consumer-b',categories=['food'],malls=['mall-b'])
        s.api('/api/promotions','merchant-b',dict(shop_id='shop-a',branch_ids=['branch-a'],title='x',body='x',due_at=500,expires_at=900),status=404,code='not_found')
        for branches in ([],['branch-a','branch-a']):
            s.api('/api/promotions','merchant-a',dict(shop_id='shop-a',branch_ids=branches,title='x',body='x',due_at=500,expires_at=900),status=400,code='invalid_request')
        s.api('/api/promotions','merchant-a',dict(shop_id='shop-a',branch_ids=['branch-b'],title='x',body='x',due_at=500,expires_at=900),status=404,code='not_found')
        p=s.promotion(title='  <em>Offer</em>  ',branch_ids=['branch-off','branch-a2','branch-a'])
        c.require(s.inbox()==[],'Creation is not delivery')
        c.require(s.dispatch()==2,'Category AND selected participating mall audience')
        first=s.inbox()[0];second=s.inbox('consumer-b')[0]
        c.require(first['branch_ids']==['branch-a2','branch-a'] and second['branch_ids']==['branch-a2'],'Only eligible branches in original order')
        c.require(first['title']=='<em>Offer</em>' and first['delivered_at']==600,'Copied normalized content and configured clock')
        s.api('/api/promotions/'+quote(p['id'],safe='')+'/cancel','merchant-b',{},status=404,code='not_found')
        s.api('/api/promotions/'+quote(p['id'],safe='')+'/cancel','merchant-a',{})
        s.preferences(categories=[],malls=[])
        c.require(s.inbox()==[first],'Cancel and opt-out retain old message')
        promotions=s.api('/api/promotions','merchant-a')['promotions'];c.require(promotions[0]['delivered_count']==2,'Aggregate lifetime delivery count')
        c.require(not any(key in json.dumps(promotions) for key in ('consumer-a','consumer-b')),'Merchant sees no recipient identity')
        app.set_clock(720)
        s.preferences('consumer-a',categories=['leisure'],malls=['mall-a'])
        s.preferences('consumer-b',categories=['food'],malls=['mall-b'])
        s.promotion('wrong category or mall',branch_ids=['branch-a'])
        c.require(s.dispatch()==0,'Both category and matching mall required')
        s.preferences('consumer-a',categories=['food'],malls=['mall-a'])
        s.api('/api/branches/branch-a','admin',{'participating':False},method='PATCH')
        c.require(s.dispatch()==0,'Dispatch checks current participation')
        s.api('/api/branches/branch-a','admin',{'participating':True},method='PATCH')
        c.require(s.dispatch()==1,'Eligibility restoration permits undelivered promotion')
        with browser_session() as browser:
            page=browser.new_page();browser_login(page,app,'consumer-b');expect(page.locator('[data-message-id]')).to_have_count(1)
            expect(page.locator('#inbox')).to_contain_text('<em>Offer</em>');c.require(page.locator('#inbox em').count()==0,'Inbox text rendered literally')
            page.locator('#preference-categories').fill('["leisure"]');page.locator('#preference-malls').fill('["mall-a"]')
            with page.expect_response(lambda response: response.url.endswith('/api/preferences') and response.request.method=='PUT') as acknowledged:
                page.locator('#save-preferences').click()
            c.require(acknowledged.value.status==200,'Preference write acknowledged')
            saved=s.api('/api/preferences','consumer-b')['preferences']
            c.require(saved['categories']==['leisure'] and saved['mall_ids']==['mall-a'],'Browser preference mutation reaches server')


def cooldown(c):
    with Application() as app:
        s=Session(app,c);s.preferences()
        future=s.promotion('future boundary',due_at=900)
        for now in (600,899):
            app.set_clock(now)
            c.require(s.dispatch()==0 and s.inbox()==[],'Future promotion does not deliver before due time')
            row=next(p for p in s.api('/api/promotions','merchant-a')['promotions'] if p['id']==future['id'])
            c.require(row['delivered_count']==0,'Early dispatch does not change lifetime count')
        app.set_clock(900)
        c.require(s.dispatch()==1,'Exact due time eligible; early dispatch did not consume cooldown')
        c.require([m['promotion_id'] for m in s.inbox()]==[future['id']],'Due promotion reaches its consumer')
    with Application() as app:
        s=Session(app,c);s.preferences(categories=['food','leisure'],malls=['mall-a','mall-b'])
        s.promotion('expired',due_at=1,expires_at=600)
        cancelled=s.promotion('cancelled',due_at=2)
        s.api('/api/promotions/'+quote(cancelled['id'],safe='')+'/cancel','merchant-a',{})
        first=s.promotion('first',due_at=500);s.promotion('second',due_at=500)
        s.promotion('third merchant',who='merchant-b',shop_id='shop-b',branch_ids=['branch-b'],due_at=501)
        # Warm tokens before independent simultaneous HTTP requests.
        admin=s.token('admin')
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes=list(pool.map(lambda _:request(app,'/api/dispatch',{'now':999999,'cooldown':0},token=admin),range(12)))
        c.require(all(r['status']==200 for r in outcomes) and sum(r['body']['delivered_count'] for r in outcomes)==1,'Concurrent dispatch once, ignores client clock')
        c.require([r['title'] for r in s.inbox()]==['first'],'Due then creation order, skip cancelled and expired')
        app.set_clock(719);c.require(s.dispatch()==0,'119 seconds suppressed')
        app.set_clock(720);c.require(s.dispatch()==1,'120 seconds eligible')
        c.require([r['title'] for r in s.inbox()]==['first','second'],'Equal due order stable')
        s.restart();app.set_clock(839);c.require(s.dispatch()==0,'Cooldown durable across restart and merchants')
        app.set_clock(840);c.require(s.dispatch()==1,'Cross-merchant next delivery after cooldown')
        app.set_clock(960);c.require(s.dispatch()==0,'Lifetime consumer-promotion uniqueness')
        s.preferences(categories=[],malls=[]);s.preferences(categories=['food'],malls=['mall-a']);c.require(s.dispatch()==0,'Opt-out/in does not resend')
        s.preferences('consumer-b');c.require(s.dispatch()==1,'New eligible consumer unaffected by another consumer cooldown')
        c.require(s.inbox('consumer-b')[0]['promotion_id']==first['id'],'Independent consumer receives first pending eligible promotion')


def review(c):
    with Application() as app:
        s=Session(app,c);row,payload=s.receipt(amount=749)
        c.require(s.api('/api/receipts',body=payload)['receipt']['id']==row['id'],'Matching request replay')
        s.api('/api/receipts',body=dict(payload,amount_cents=750),status=409,code='request_conflict')
        asset,_=s.photo('consumer-b')
        s.api('/api/receipts','consumer-b',dict(payload,request_id='other',asset_id=asset['id']),status=409,code='duplicate_receipt')
        s.api('/api/receipts/'+quote(row['id'],safe='')+'/review',body={'decision':'approved'},status=403,code='forbidden')
        s.api('/api/branches/branch-a','admin',{'participating':False},method='PATCH')
        s.review(row,status=422,code='not_participating')
        c.require(s.api('/api/receipts',body=payload)['receipt']['status']=='pending','Replay despite participation change')
        s.api('/api/branches/branch-a','admin',{'participating':True},method='PATCH')
        admin=s.token('admin');path='/api/receipts/'+quote(row['id'],safe='')+'/review'
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes=list(pool.map(lambda _:request(app,path,{'decision':'approved','points':999,'reviewed_by':'forged'},token=admin),range(12)))
        c.require(all(r['status']==200 for r in outcomes),'Concurrent review retries succeed')
        approved=outcomes[0]['body']['receipt'];c.require(approved['points']==2 and approved['reviewed_by']=='admin','Floor cents/250 and actual reviewer')
        wallet=s.api('/api/wallet');c.require(wallet['balance']==2 and len(wallet['ledger'])==1 and wallet['ledger'][0]['delta']==2,'Single atomic credit')
        s.review(row,'rejected',status=409,code='review_conflict')
        rejected,rejected_payload=s.receipt('reject',amount=1000);s.review(rejected,'rejected');s.review(rejected,'rejected')
        replacement=s.api('/api/receipts',body=dict(rejected_payload,request_id='replacement'),status=201)['receipt']
        c.require(s.api('/api/receipts',body=rejected_payload)['receipt']['status']=='rejected','Old request replays rejected even after replacement')
        zero,_=s.receipt('zero',amount=0);s.review(zero)
        wallet=s.api('/api/wallet');c.require(wallet['balance']==2 and len(wallet['ledger'])==2 and wallet['ledger'][-1]['delta']==0,'Zero point approval still ledger entry')
        rows=s.api('/api/receipts')['receipts'];c.require(rows[0]['id']==replacement['id'],'Pending-first ordering')
        s.restart();c.require(s.api('/api/wallet')==wallet,'Credit ledger persists')
        c.require(s.api('/api/receipts',body=payload)['receipt']['points']==2,'Reviewed request durable replay')
        with browser_session() as browser:
            page=browser.new_page();browser_login(page,app,'admin')
            selector=page.locator('[data-receipt-id]').filter(has=page.locator('[data-approve]'))
            target=page.locator('[data-receipt-id]').filter(has_text='replacement')
            expect(target).to_have_count(1);target.locator('[data-approve]').click()
            expect(target).to_contain_text('approved')
            c.require(s.api('/api/wallet')['balance']==6,'Browser review causes actual credit')


def rewards(c):
    with Application() as app:
        s=Session(app,c)
        s.api('/api/redemptions',body={'request_id':'retry','reward_id':'reward-a'},status=409,code='insufficient_points')
        row,_=s.receipt('fund-a',amount=1000);s.review(row)
        row,_=s.receipt('fund-b','consumer-b',amount=1000);s.review(row)
        tokens=[s.token('consumer-a'),s.token('consumer-b')]
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes=list(pool.map(lambda index:request(app,'/api/redemptions',{'request_id':'competition-'+str(index),'reward_id':'reward-b'},token=tokens[index%2]),range(12)))
        c.require(sum(r['status']==201 for r in outcomes)==1 and all(r['status'] in (201,409) for r in outcomes),'Final shared stock cannot over-reserve')
        result=s.api('/api/redemptions',body={'request_id':'retry','reward_id':'reward-a','cost':0,'owner_id':'consumer-b'},status=201)['redemption']
        c.require(result['owner_id']=='consumer-a' and result['cost']==2 and result['status']=='reserved','Failed key reusable, owner and price server controlled')
        s.api('/api/redemptions',body={'request_id':'retry','reward_id':'reward-b'},status=409,code='request_conflict')
        before=s.api('/api/wallet');c.require(s.api('/api/redemptions',body={'request_id':'retry','reward_id':'reward-a'})['redemption']==result,'Exact matching retry result')
        c.require(s.api('/api/wallet')==before,'Retry no second debit')
        running=0
        for entry in before['ledger']:
            running+=entry['delta'];c.require(entry['balance']==running,'Historical ledger balance')
        c.require(before['balance']==running and running>=0,'Current balance equals deltas')
        s.api('/api/wallet','merchant-a',status=403,code='forbidden')
        s.restart();c.require(s.api('/api/wallet')==before,'Reservation and debit durable')
        s.api('/api/redemptions',body={'request_id':'empty','reward_id':'reward-b'},status=409,code='out_of_stock')
        with browser_session() as browser:
            page=browser.new_page();browser_login(page,app,'consumer-b')
            page.locator('#redemption-key').fill('browser-reserve');page.locator('#redemption-reward').select_option('reward-a');page.locator('#redeem').click()
            expect(page.locator('#redemptions')).to_contain_text('reward-a')
            wallet=s.api('/api/wallet','consumer-b');c.require(any(r['request_id']=='browser-reserve' for r in wallet['redemptions']),'Browser stores real reservation')
            previous=wallet['balance'];page.locator('#redeem').click();expect(page.locator('#error')).to_have_text('')
            c.require(s.api('/api/wallet','consumer-b')['balance']==previous,'Browser explicit request key retry')


GATES=[('RU-001',directory),('RU-002',images),('RU-003',audience),('RU-004',cooldown),('RU-005',review),('RU-006',rewards)]

def main():
    results=[]
    for identity,gate in GATES:
        checks=Checks()
        try:
            gate(checks);passed=True;detail='Behavioral contract passed'
        except Exception as error:
            passed=False;detail=type(error).__name__+': '+str(error)
        results.append({'ru_id':identity,'passed':passed,'detail':detail,'checks_passed':checks.count})
    result={'harness_ok':True,'results':results,'infrastructure_errors':[]}
    print(json.dumps(result));return result

if __name__=='__main__':main()
