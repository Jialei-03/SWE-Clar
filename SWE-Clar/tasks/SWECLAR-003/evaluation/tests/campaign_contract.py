"""Independent static output, DOM, storage and network checks."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from pathlib import Path
from copy import deepcopy
import base64,json,os,sys,traceback
from urllib.parse import urlsplit
from urllib.request import urlopen
sys.path.insert(0,'/public_tests')
from campaign_support import Site
from test_public import visible_build,visible_layout
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
PROJECT=os.environ.get('SWECLAR_PROJECT_DIR','/workspace')

def built(site,spec,output=None):
    out,result=site.build(spec,output);assert result=={'index_file':'index.html'},result;return out

def ru001():
    with Site(PROJECT) as site:
        visible_build(site)
        for change in [{'title':''},{'locale':'invalid-locale'},{'site_id':'../invalid'},{'campaigns':[]},{'extra':1},{'legal':{'privacy':'https://example.test','terms':'#terms','disclosure':'#disclosure'}},{'consent_decision':'unknown'}]:
            _,result=site.build({**site.spec,**change});assert result=={'error':{'code':'invalid_spec'}}
        missing=deepcopy(site.spec);missing.pop('title');assert site.build(missing)[1]=={'error':{'code':'invalid_spec'}}
        # Consent-control identities are reserved, not legal-section targets.
        out=built(site,site.spec);before=site.files(out)
        for field in ['privacy','terms','disclosure']:
            for target in ['#accept','#decline']:
                bad=deepcopy(site.spec);bad['legal'][field]=target
                assert site.build(bad,out)[1]=={'error':{'code':'invalid_spec'}}
                assert site.files(out)==before
        # Reserve exact IDs only; similarly prefixed legal anchors stay valid.
        good=deepcopy(site.spec)
        good['legal']={'privacy':'#accept-policy','terms':'#decline-policy','disclosure':'#legal-notice'}
        built(site,good)

def ru002():
    with Site(PROJECT) as site:
        spec=deepcopy(site.spec);spec['campaigns']*=2;spec['title']='X'*160;spec['description']='Y'*600
        for card in spec['campaigns']:card['name']='Z'*120
        out=built(site,spec)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(site.serve(out))
                for width in [320,375,599,600,800,1023,1024,1440]:visible_layout(page,6,width)
            finally:browser.close()

def ru003():
    with Site(PROJECT) as site:
        spec=deepcopy(site.spec);spec.update(locale='fr-FR',title='Literal {{CARDS}} & <b>title</b>',description='A "quoted" <description> & literal text')
        spec['campaigns'][1]['name']='<img src=x onerror="window.injected=true">';spec['available_assets'].extend(['unused.svg','missing-unreferenced.svg']);site.command("from pathlib import Path; import shutil,sys; shutil.copyfile(Path(sys.argv[1])/'hero.svg',Path(sys.argv[1])/'unused.svg')",site.work/'assets')
        out=built(site,spec);before=site.files(out);assets=site.files(site.work/'assets');assert not any('unused.svg' in k for k in before)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();url=site.serve(out);page.goto(url)
                assert page.locator('html').get_attribute('lang')=='fr-FR';assert page.title()==spec['title']
                assert page.locator('meta[name=description]').get_attribute('content')==spec['description']
                assert page.locator('h1').text_content()==spec['title'];expect(page.locator('#hero')).to_contain_text(spec['description'],use_inner_text=True)
                assert page.locator('.campaign-card h2').all_text_contents()==[c['name'] for c in spec['campaigns']]
                assert page.evaluate('window.injected===undefined')
                cards=page.locator('.campaign-card');ids=cards.evaluate_all('(nodes)=>nodes.map(n=>n.id)');assert all(ids) and len(set(ids))==len(ids)
                images=[page.locator('#hero img'),*page.locator('.campaign-card img').all()]
                names=[spec['hero_asset'],*[c['asset'] for c in spec['campaigns']]]
                for image,name in zip(images,names):
                    expect(image).to_be_visible();page.wait_for_function('(src)=>Array.from(document.images).filter(i=>i.src===src).every(i=>i.complete&&i.naturalWidth>0)',arg=image.evaluate('(i)=>i.src'))
                    with urlopen(image.evaluate('(i)=>i.src'),timeout=5) as response:assert base64.b64encode(response.read()).decode()==assets[name]
            finally:browser.close()
        for name in ['missing.svg','../hero.svg','https://example.test/hero.svg','/hero.svg']:
            bad=deepcopy(spec);bad['hero_asset']=name;assert site.build(bad,out)[1]=={'error':{'code':'invalid_asset'}};assert site.files(out)==before
        absolute=deepcopy(spec);absolute['hero_asset']=str(site.work/'assets/hero.svg');absolute['available_assets'].append(absolute['hero_asset']);assert site.build(absolute,out)[1]=={'error':{'code':'invalid_asset'}};assert site.files(out)==before
        missing=deepcopy(spec);missing['available_assets'].remove('hero.svg');assert site.build(missing,out)[1]=={'error':{'code':'invalid_asset'}};assert site.files(out)==before
        site.command("from pathlib import Path; import sys; (Path(sys.argv[1])/'linked.svg').symlink_to(Path(sys.argv[1])/'hero.svg')",site.work/'assets')
        bad=deepcopy(spec);bad['hero_asset']='linked.svg';bad['available_assets'].append('linked.svg');assert site.build(bad,out)[1]=={'error':{'code':'invalid_asset'}};assert site.files(out)==before
        fresh=site.outputs/'fresh-invalid';assert site.build(bad,fresh)[1]=={'error':{'code':'invalid_asset'}};assert site.files(fresh)=={}
        invalid=deepcopy(spec);invalid['title']='';assert site.build(invalid,out)[1]=={'error':{'code':'invalid_spec'}};assert site.files(out)==before
        site.command("from pathlib import Path; import sys; (Path(sys.argv[1])/'old.txt').write_text('old')",out)
        built(site,spec,out);assert site.files(out)==before

def ru004():
    with Site(PROJECT) as site:
        spec=deepcopy(site.spec);out=built(site,spec);key='campaign:'+spec['site_id']+':consent'
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();url=site.serve(out);page.goto(url);expect(page.locator('#consent')).to_be_visible();assert page.evaluate('(k)=>localStorage.getItem(k)',key) is None
                page.locator('#accept').click();expect(page.locator('#consent')).to_be_hidden();assert page.evaluate('(k)=>localStorage.getItem(k)',key)=='accept'
                page.reload();expect(page.locator('#consent')).to_be_hidden()
                page.evaluate('(k)=>localStorage.setItem(k,"corrupt")',key);page.reload();expect(page.locator('#consent')).to_be_visible();page.locator('#decline').click();assert page.evaluate('(k)=>localStorage.getItem(k)',key)=='decline'
                override={**spec,'consent_decision':'accept'};built(site,override,out);page.reload();expect(page.locator('#consent')).to_be_hidden();assert page.evaluate('(k)=>localStorage.getItem(k)',key)=='accept'
                override['consent_decision']='decline';built(site,override,out);page.reload();assert page.evaluate('(k)=>localStorage.getItem(k)',key)=='decline'
                other={**spec,'site_id':'another-site'};built(site,other,out);page.reload();expect(page.locator('#consent')).to_be_visible();assert page.evaluate('localStorage.getItem("campaign:another-site:consent")') is None
                built(site,spec,out);page.reload();expect(page.locator('#consent')).to_be_hidden()
                links=page.locator('#footer a').all();assert sorted(link.get_attribute('href') for link in links)==sorted(spec['legal'].values())
                for link in links:
                    target=link.get_attribute('href');assert page.locator(target).count()==1;link.click();assert urlsplit(page.url).fragment==target[1:];expect(page.locator(target)).to_be_visible()
            finally:browser.close()

def fill(page,name,email,message):
    # The agreement fixes field names, not input-vs-textarea markup.
    form=page.locator('#contact form')
    form.locator('[name=name]').fill(name);form.locator('[name=email]').fill(email);form.locator('[name=message]').fill(message)
    form.locator('button[type=submit],button:not([type]),input[type=submit]').click()

def ru005():
    with Site(PROJECT) as site:
        spec=deepcopy(site.spec);out=built(site,spec);key='campaign:'+spec['site_id']+':outbox'
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();url=site.serve(out);network=[]
                def route(request):
                    if request.request.url.startswith(url+'/') and request.request.method=='GET':request.continue_()
                    else:network.append({'url':request.request.url,'method':request.request.method});request.abort()
                page.route('**/*',route);page.goto(url);page.locator('#decline').click()
                for malformed in ['{bad','{}','[{}]']:
                    page.evaluate('(args)=>localStorage.setItem(...args)',[key,malformed]);page.reload();expect(page.locator('#outbox-count')).to_have_text('Requests: 0')
                fill(page,'  Visitor  ',' PERSON@EXAMPLE.TEST ','  Local message  ');expect(page.locator('#form-status')).to_have_text('saved_locally')
                rows=page.evaluate('(k)=>JSON.parse(localStorage.getItem(k))',key);assert len(rows)==1 and set(rows[0])=={'request_id','name','email','message'};assert rows[0]['name']=='Visitor' and rows[0]['email']=='person@example.test' and rows[0]['message']=='Local message' and isinstance(rows[0]['request_id'],str) and rows[0]['request_id']
                for field in ['name','email','message']:expect(page.locator('#contact form [name='+field+']')).to_have_value('')
                for data in [(' ','person@example.test','message'),('n','bad-email','message'),('n','a@@b.test','m'),('n','a@b.test',' '),('n'*81,'a@b.test','m'),('n','a'*250+'@b.test','m'),('n','a@b.test','m'*2001)]:
                    page.reload();expect(page.locator('#form-status')).to_have_text('')
                    fill(page,*data);expect(page.locator('#form-status')).to_have_text('invalid_contact');assert page.evaluate('(k)=>JSON.parse(localStorage.getItem(k))',key)==rows
                    expect(page.locator('#contact form [name=name]')).to_have_value(data[0]);expect(page.locator('#contact form [name=message]')).to_have_value(data[2])
                for _ in range(2):fill(page,'Visitor','person@example.test','Local message');expect(page.locator('#form-status')).to_have_text('saved_locally')
                rows=page.evaluate('(k)=>JSON.parse(localStorage.getItem(k))',key);assert len(rows)==3 and len({row['request_id'] for row in rows})==3
                page.reload();expect(page.locator('#outbox-count')).to_have_text('Requests: 3')
                other={**spec,'site_id':'second-site','consent_decision':'accept'};built(site,other,out);page.reload();expect(page.locator('#outbox-count')).to_have_text('Requests: 0');fill(page,'Second','two@example.test','Message');expect(page.locator('#outbox-count')).to_have_text('Requests: 1')
                assert page.evaluate('(k)=>JSON.parse(localStorage.getItem(k))',key)==rows
                for resource in page.locator('script[src],link[rel=stylesheet],img').all():
                    value=resource.get_attribute('src') or resource.get_attribute('href');assert value and not urlsplit(value).scheme and not value.startswith('//')
                assert not network,network
            finally:browser.close()

def main():
    results=[]
    for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
        try:test();passed=True;detail='passed'
        except (AssertionError,BrowserTimeout) as error:passed=False;detail=traceback.format_exc()[-2200:]
        results.append({'ru_id':f'RU-{i:03d}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':results}
if __name__=='__main__':
    try:print(json.dumps(main()))
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[type(error).__name__+': '+str(error)],'traceback':traceback.format_exc()}));raise SystemExit(2)
