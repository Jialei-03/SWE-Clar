"""Ordinary-user UI driver. Assertions and expected business results stay in evaluator."""
import json,sys
from playwright.sync_api import sync_playwright
request=json.loads(sys.stdin.read())
with sync_playwright() as p:
    try:browser=p.chromium.launch(headless=True)
    except Exception as error:
        print(json.dumps({'infrastructure_error':'Prepared browser launch failed: '+str(error)}))
        sys.exit(2)
    try:
        page=browser.new_page(viewport={'width':900,'height':1100});page.set_default_timeout(5000)
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(request['url']) else route.abort())
        page.goto(request['url'])
        first=page.locator('#groups section').filter(has=page.get_by_role('heading',name=request['initial_name'],exact=True))
        first.get_by_label('Group name').fill(request['name'])
        first.get_by_role('button',name='Save name').click()
        page.get_by_role('heading',name=request['name'],exact=True).wait_for()
        page.locator('#search').fill(request['query'])
        page.wait_for_function("q => document.querySelector('#search').value === q",arg=request['query'])
        # Wait on the actual async render, not a fixed sleep.
        page.wait_for_function("n => [...document.querySelectorAll('#groups h2')].length>0 && [...document.querySelectorAll('#groups h2')].every(e=>e.textContent===n)",arg=request['name'])
        images=page.locator('section img').evaluate_all("async imgs=>{await Promise.all(imgs.map(i=>i.decode()));return imgs.map(i=>({width:i.naturalWidth,height:i.naturalHeight,src:i.getAttribute('src')}));}")
        page.reload();page.get_by_role('heading',name=request['name'],exact=True).wait_for()
        print(json.dumps({'images':images,'restored':True}))
    finally:browser.close()
