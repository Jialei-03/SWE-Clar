import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar')
from harness import App
from preflight import preflight
from playwright.sync_api import sync_playwright
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
FLAGS=['--use-angle=swiftshader','--enable-unsafe-swiftshader']


def command(app,type_,**fields):return app.request('/api/command',dict(type=type_,**fields))
def unit_template(id='TEST',**changes):
    return dict(id=id,name='Synthetic unit',kind='melee',health=40,attack=8,defense=2,speed=2,range=.9,cooldown=5,projectile_speed=8,**changes) if not changes else {**unit_template(id),**changes}
def pixels(page,points):
    return page.evaluate('''points=>{const c=document.querySelector('#arena'),gl=c.getContext('webgl'),r=c.getBoundingClientRect();
      return points.map(point=>{const p=window.arenaView.project(point),v=new Uint8Array(4);
        gl.readPixels(Math.floor(p.x-r.left),Math.floor(c.height-(p.y-r.top)),1,1,gl.RGBA,gl.UNSIGNED_BYTE,v);return Array.from(v);});}''',points)
def open_page(browser,app):
    page=browser.new_page(viewport={'width':1280,'height':900});page.set_default_timeout(5000);page.goto(app.url)
    page.wait_for_function("window.arenaView?.data && document.querySelector('#arena').width>300")
    return page


def workshop():
    with App(PROJECT) as app,sync_playwright() as p:
        command(app,'clear');command(app,'place',id='LEFT',template_id='GUARD',team='A',x=-3,z=0)
        command(app,'place',id='RIGHT',template_id='SCOUT',team='B',x=3,z=0)
        browser=_isolated_browser_launch(p.chromium, headless=True, args=FLAGS)
        try:
            page=open_page(browser,app);before=app.request('/api/state')
            color=pixels(page,[{'x':-3,'y':.6,'z':0},{'x':3,'y':.6,'z':0}])
            assert color[0][2]>color[0][0]+70 and color[1][0]>color[1][2]+70,color
            assert page.locator('[data-unit]').count()==2
            original=page.locator('#arena').evaluate('(c)=>c.toDataURL()')
            page.locator('#camera-side').click();changed=page.locator('#arena').evaluate('(c)=>c.toDataURL()');assert changed!=original
            assert app.request('/api/state')==before
            page.locator('#names').uncheck();assert page.locator('[data-unit]').count()==0
            page.locator('#names').check();assert page.locator('[data-unit]').count()==2
            yaw=page.evaluate('window.arenaView.yaw');box=page.locator('#arena').bounding_box()
            page.mouse.move(box['x']+400,box['y']+300);page.mouse.down(button='right');page.mouse.move(box['x']+440,box['y']+320,steps=5);page.mouse.up(button='right')
            assert page.evaluate('window.arenaView.yaw')!=yaw
            zoom=page.evaluate('window.arenaView.zoom');page.mouse.wheel(0,150);page.wait_for_function('(z)=>window.arenaView.zoom!==z',arg=zoom)
            assert app.request('/api/state')==before
            page.locator('#placement-id').fill('PLACED');page.locator('#team').select_option('B')
            point=page.evaluate('window.arenaView.project({x:0,y:0,z:3})')
            with page.expect_response('**/api/command'):page.mouse.click(point['x'],point['y'])
            state=app.request('/api/state');placed=next(x for x in state['config']['placements'] if x['id']=='PLACED')
            assert placed['team']=='B' and abs(placed['x'])<.03 and abs(placed['z']-3)<.03
            assert page.locator('[data-unit="PLACED"]').count()==1
            with page.expect_response('**/api/command'):page.locator('[data-remove-unit="PLACED"]').click()
            with page.expect_response('**/api/command'):page.locator('#start').click()
            page.wait_for_function('async()=>{const s=await(await fetch("/api/state")).json();return s.battle?.tick>=2}')
            page.locator('#pause').click();page.wait_for_timeout(250)
            tick=app.request('/api/state')['battle']['tick']
            with page.expect_response('**/api/command'):page.locator('#step').click()
            assert app.request('/api/state')['battle']['tick']==tick+1
            with page.expect_response('**/api/command'):page.locator('#reset').click()
            assert app.request('/api/state')['battle'] is None
        finally:browser.close()


def catalog():
    with App(PROJECT) as app,sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True, args=FLAGS)
        try:
            page=open_page(browser,app);page.locator('#template-id').fill('CUSTOM');page.locator('#template-name').fill('<b>Custom unit</b>');page.locator('#stat-health').fill('55')
            with page.expect_response('**/api/command'):page.locator('#template-form button[type="submit"]').click()
            state=app.request('/api/state');custom=next(x for x in state['config']['templates'] if x['id']=='CUSTOM');assert custom['health']==55
            assert page.url==app.url+'/'
            command(app,'clear');command(app,'place',id='ONE',template_id='CUSTOM',team='A',x=-2,z=0);command(app,'place',id='TWO',template_id='CUSTOM',team='B',x=2,z=0)
            page.reload();page.wait_for_function("window.arenaView?.data?.config.placements.length===2")
            assert page.locator('#labels b').count()==0 and '<b>Custom unit</b>' in page.locator('#labels').inner_text()
            config=app.request('/api/state')['config'];battle=command(app,'start')['battle']
            assert all(x['hp']==55 and x['health']==55 for x in battle['units'])
            assert app.request('/api/state')['config']==config
            command(app,'reset');app.stop();app.start();assert app.request('/api/state')=={'config':config,'battle':None}
        finally:browser.close()
        before=app.request('/api/state')
        invalid=[{'type':'place','id':'OVER','template_id':'CUSTOM','team':'A','x':-2.2,'z':0},
                 {'type':'place','id':'OUT','template_id':'CUSTOM','team':'A','x':8,'z':0},
                 {'type':'place','id':'BAD','template_id':'MISSING','team':'A','x':0,'z':3},
                 {'type':'delete_template','id':'CUSTOM'}, {'type':'limit','value':True},
                 {'type':'template','value':dict(custom,health=True)}, {'type':'template','value':dict(custom,speed=float('inf'))}]
        for value in invalid:app.request('/api/command',value,status=400);assert app.request('/api/state')==before
        command(app,'remove',id='ONE');command(app,'remove',id='TWO');command(app,'delete_template',id='CUSTOM')
        assert not any(x['id']=='CUSTOM' for x in app.request('/api/state')['config']['templates'])


def run():workshop();catalog();print('Public 3D workshop and template checks passed')
if __name__=='__main__':preflight();run()
