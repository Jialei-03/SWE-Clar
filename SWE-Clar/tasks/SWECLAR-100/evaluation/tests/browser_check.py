import json,os,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright

def exercise(url,temp,publish_next,mode):
 proof=temp/'browser-proof.json';result={};os.environ['REPORT_PRIVATE_SENTINEL']='private-canary'
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/public_tests/browser_launcher.py',headless=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  try:
   identity=json.loads(proof.read_text());status=dict(line.split(':',1) for line in Path('/proc/'+str(identity['pid'])+'/status').read_text().splitlines() if ':' in line);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0;assert 'REPORT_PRIVATE_SENTINEL' not in identity['environment_keys'];identity['live_pid_verified']=True
   Path('/private/results').mkdir(parents=True,exist_ok=True)
   with open('/private/results/browser-isolation.jsonl','a') as f:f.write(json.dumps(identity)+'\n')
   context=browser.new_context(viewport={'width':900,'height':1000});page=context.new_page();page.set_default_timeout(5000);page.goto(url)
   page.locator('summary').click();page.locator('#token').fill('synthetic-device');page.locator('#connect button').click();page.locator('#sync').click();page.wait_for_function("document.querySelectorAll('[data-category]').length===2")
   result['category_order']=page.locator('[data-category]').evaluate_all('(ns)=>ns.map(n=>n.dataset.category)');page.locator('[data-category="category-a"]').click();result['product_order']=page.locator('[data-product]').evaluate_all('(ns)=>ns.map(n=>n.dataset.product)')
   assert page.locator('#content img').count()==2;page.wait_for_function("[...document.querySelectorAll('#content img')].every(n=>n.complete&&n.naturalWidth>0)");result['images']=True
   page.locator('[data-product="product-a"]').click();controls=['#logo','#back','#sync','#connect button','#settings button','header label','#connect label','#settings label','summary'];english=[page.locator(sel).inner_text().strip() for sel in controls];page.locator('#language').select_option('es');translated=[page.locator(sel).inner_text().strip() for sel in controls];result['translated']=page.locator('#heading').inner_text().startswith('Estante') and all(text and text!=old for text,old in zip(translated,english));
   if mode=='content':return result
   page.locator('#logo').click();result['logo_category']=page.locator('[data-product="product-a"]').count()==1;page.locator('#back').click();result['back_product']=page.locator('.detail').count()==1;page.locator('#back').click();result['back_category']=page.locator('[data-product="product-a"]').count()==1
   result['layouts']=[]
   for width in [360,768,1024]:
    page.set_viewport_size({'width':width,'height':1000});result['layouts'].append(page.evaluate("()=>({overflow:document.documentElement.scrollWidth>innerWidth,truncated:[...document.querySelectorAll('.card span')].some(n=>n.scrollHeight>n.clientHeight)})"))
   if mode=='navigation':return result
   saved=page.evaluate("localStorage.getItem('kiosk-content')");result['no_token']='synthetic-device' not in saved
   # A newer two-image publication must stay uncommitted when either image fails.
   # Exercise both target assets so either legal fetch ordering encounters a later failure.
   next_snapshot=publish_next()
   def rendered():
    return page.evaluate("""()=>({heading:document.querySelector('#heading').textContent,content:document.querySelector('#content').textContent,images:[...document.querySelectorAll('#content img')].map(img=>{const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext('2d').drawImage(img,0,0);return c.toDataURL()})})""")
   previous=rendered();attempts=[]
   for failure in ['checksum','decode','http']:
    for target in ['art','art-b']:
     served=[]
     def invalid_snapshot(route):
      # Use the independently fetched publication, avoiding nested synchronous
      # route.fetch callbacks and double-handled routes during failed assets.
      data=json.loads(json.dumps(next_snapshot))
      if failure=='decode':data['assets'][target]['sha256']=hashlib.sha256(b'broken-image').hexdigest()
      route.fulfill(json=data)
     def asset_response(route):
      ident=route.request.url.rsplit('/',1)[-1]
      if ident==target:
       served.append({'asset':ident,'valid':False})
       route.fulfill(status=503 if failure=='http' else 200,body='broken-image',content_type='image/svg+xml')
      else:
       assert ident in ('art','art-b')
       body=(temp/(ident+'.svg')).read_bytes()
       served.append({'asset':ident,'valid':True});route.fulfill(status=200,body=body,content_type='image/svg+xml')
     page.route('**/snapshot',invalid_snapshot);page.route('**/asset/*',asset_response)
     # Await the injected asset response, not just an already-idle page state
     # after snapshot headers. SHA verification starts after body consumption.
     with page.expect_response('**/asset/'+target) as bad_asset:
      with page.expect_response('**/snapshot'):page.locator('#sync').click()
     bad_asset.value.finished()
     page.wait_for_timeout(600)
     page.wait_for_load_state('networkidle')
     attempts.append({'failure':failure,'target':target,'served':list(served),'retained':page.evaluate("localStorage.getItem('kiosk-content')")==saved and rendered()==previous})
     page.unroute('**/asset/*');page.unroute('**/snapshot')
   result['atomic_attempts']=attempts
   result['atomic']=all(x['retained'] and any(r['asset']==x['target'] and not r['valid'] for r in x['served']) for x in attempts)
   result['atomic']=result['atomic'] and all(any(x['failure']==failure and any(r['valid'] for r in x['served']) for x in attempts) for failure in ['checksum','decode','http'])
   page.evaluate('navigator.serviceWorker.ready');context.set_offline(True);page.reload();page.locator('[data-category="category-a"]').click();assert page.locator('#content img').count()==2;page.wait_for_function("[...document.querySelectorAll('#content img')].every(n=>n.complete&&n.naturalWidth>0)");result['offline_cache']=True;context.set_offline(False)
   page.locator('summary').click();page.locator('#token').fill('synthetic-device');page.locator('#connect button').click();delayed_snapshot=publish_next();held=[]
   page.route('**/snapshot',lambda route:held.append(route));page.locator('#sync').click()
   for _ in range(50):
    if held:break
    page.wait_for_timeout(20)
   assert held,'sync did not fetch snapshot'
   assert delayed_snapshot['version']>json.loads(saved)['version'];page.locator('#token').fill('different-session');page.locator('#connect button').click();held[0].fulfill(json=delayed_snapshot);page.wait_for_load_state('networkidle');result['stale']=page.evaluate("localStorage.getItem('kiosk-content')")==saved
   return result
  finally:browser.close()
