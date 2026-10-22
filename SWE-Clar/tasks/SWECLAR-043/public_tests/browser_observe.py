"""Public browser transport; expectations remain in the protected evaluator."""
import json,sys
from playwright.sync_api import sync_playwright
request=json.load(sys.stdin)
with sync_playwright() as p:
    try:browser=p.chromium.launch(headless=True)
    except Exception as error:
        print(json.dumps({'infrastructure_error':str(error)}));sys.exit(2)
    try:
        page=browser.new_page();page.set_default_timeout(5000);page.goto(request['url'])
        for step in request['steps']:
            page.get_by_label('Action',exact=True).select_option(step['type'])
            for name,key in [('Receiver','receiver'),('Rejection reason','reason')]:
                page.get_by_label(name,exact=True).fill(step.get(key,''))
            if step.get('upload'):
                page.get_by_label('Photo file',exact=True).set_input_files({'name':'synthetic.txt','mimeType':'text/plain','buffer':b'synthetic proof file'})
            with page.expect_response(lambda r:'/api/event' in r.url and r.request.method=='POST'):
                page.get_by_role('button',name='Apply event',exact=True).click()
        page.reload()
        value=page.request.get(request['url']+'api/order').json()
        print(json.dumps({'order':value,'text':page.locator('body').inner_text()}))
    finally:browser.close()
