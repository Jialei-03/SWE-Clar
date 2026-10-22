import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
import math
import os
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar')
sys.path.insert(0,str(Path(__file__).resolve().parent))
from harness import App
from worker_support import Worker
from playwright.sync_api import sync_playwright


def drag(page, index, x, y, shift=False):
    box=page.locator(f'#point-{index}').bounding_box()
    target=page.locator('#plot').evaluate('(svg,p)=>{const m=svg.getScreenCTM();return {x:m.a*(20+5.6*p[0])+m.e,y:m.d*(380-3.6*p[1])+m.f}}',[x,y])
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
    if shift: page.keyboard.down('Shift')
    page.mouse.down();page.mouse.move(target['x'],target['y']);page.mouse.up()
    if shift: page.keyboard.up('Shift')


def run():
    project=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
    with Worker() as worker, App(project,['--driver-port',str(worker.port)]) as app:
        initial=app.request('/api/curve')
        assert initial['points']==[{'x':0,'y':0},{'x':40,'y':30},{'x':80,'y':30}]
        assert initial['revision']==0 and initial['next_sequence']==1 and initial['last_acknowledged']==0
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(app.url);page.locator('#point-2').wait_for()
                with page.expect_response(lambda r:r.url.endswith('/api/move') and r.request.method=='POST') as acknowledged:
                    drag(page,1,45,50)
                assert acknowledged.value.status==200
                page.wait_for_function("Math.abs(Number(document.querySelector('#point-1').getAttribute('cx'))-272)<1e-6 && Math.abs(Number(document.querySelector('#point-1').getAttribute('cy'))-200)<1e-6")
                edited=app.request('/api/curve')
                assert abs(edited['points'][1]['x']-45)<1e-6 and abs(edited['points'][1]['y']-50)<1e-6
                assert edited['revision']==1
                line=page.locator('#curve-line').evaluate('(line)=>({points:Array.from({length:line.points.numberOfItems},(_,i)=>{const p=line.points.getItem(i);return [p.x,p.y]}),stroke:getComputedStyle(line).stroke,display:getComputedStyle(line).display,length:line.getTotalLength()})')
                assert line['points']==[[20,380],[272,200],[468,272]]
                assert line['stroke']!='none' and line['display']!='none' and line['length']>100
                assert abs(float(page.locator('#point-1').get_attribute('cx'))-272)<1e-6
                assert abs(float(page.locator('#point-1').get_attribute('cy'))-200)<1e-6
                app.request('/api/move',{'index':1,'x':80,'y':20,'shift':False},status=400)
                assert app.request('/api/curve')==edited
                payload={'points':[{'x':10,'y':20},{'x':50,'y':40},{'x':90,'y':60}]}
                with page.expect_response(lambda r:r.url.endswith('/api/curve') and r.request.method=='POST') as acknowledged:
                    page.locator('#curve-file').set_input_files({'name':'curve.json','mimeType':'application/json','buffer':json.dumps(payload).encode()})
                assert acknowledged.value.status==200
                page.wait_for_function("Math.abs(Number(document.querySelector('#point-2').getAttribute('cx'))-524)<1e-6 && Math.abs(Number(document.querySelector('#point-2').getAttribute('cy'))-164)<1e-6")
                assert app.request('/api/curve')['points']==payload['points']
                page.locator('#positions').fill('0,30,70,100,30');page.locator('#send').click()
                page.wait_for_function("document.querySelectorAll('#samples tr').length === 5")
                assert worker.requests==[{'sequence':1,'points':payload['points'],'positions':[0,30,70,100,30]}]
                observed=[[float(s) for s in page.locator('#samples tr').nth(i).locator('td').all_text_contents()] for i in range(5)]
                assert observed==[[0,20],[30,30],[70,50],[100,60],[30,30]]
                assert worker.receipt in page.locator('#receipt').inner_text()
                page.locator('#license-uuid').fill('11111111-2222-4333-8444-555555555555')
                page.locator('#license-key').fill('DEMO-KEY-ALPHA');page.locator('#check-license').click()
                page.wait_for_function("document.querySelector('#license-result').textContent === 'Valid'")
                saved=app.request('/api/curve');app.stop();app.start();assert app.request('/api/curve')==saved
            finally:
                browser.close()
        app.request('/missing',status=404)
    with Worker() as worker, App(project,['--driver-port',str(worker.port)]) as isolated:
        assert isolated.request('/api/curve')==initial
    print('PASS: actual pointer edit, SVG coordinates, curve upload, independent TCP exchange, sample table, license UI and restart/isolation')


if __name__=='__main__': run()
