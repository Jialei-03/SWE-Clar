import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import json
import os
import struct
import sys
import time
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,'/public_tests')
from harness import App
from preflight import preflight
from source_support import Source
from test_public import capture,resolutions,control,frame,check_pixels,wait_pixel,wait_live_pixels
from playwright.sync_api import sync_playwright,Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


class FaultSource(Source):
    def __init__(self):super().__init__();self.mode='good'
    def response(self,request):
        data=super().response(request)
        if request['op']!='frame':return data
        mode=self.mode
        if mode=='bad-magic':return b'BAD1'+data[4:]
        if mode=='short-header':return data[:7]
        if mode=='truncated':return data[:-3]
        if mode=='wrong-size':return data[:12]+struct.pack('!I',len(data)-15)+data[16:]
        if mode=='zero-width':return data[:8]+b'\0\0'+data[10:]
        if mode=='oversize-width':return data[:8]+struct.pack('!H',321)+data[10:]
        if mode=='timeout':time.sleep(1.8)
        return data


def selection():
    with Source() as source:
        source.devices=[{'id':'A','name':'Auxiliary-looking name','preferred':False},
                        {'id':'Z','name':'Plain source','preferred':True},
                        {'id':'B','name':'Another source','preferred':True}]
        with App(PROJECT,['--camera-port',str(source.port)]) as app:
            state=app.request('/api/state');assert state['selected']=='B' and state['devices']==source.devices
            control(app,'device',id='Z');control(app,'resolution',value='1280x720')
            source.devices.reverse();before=app.request('/api/state')
            state=app.request('/api/scan',{});assert state==dict(before,devices=source.devices)
            source.devices=[source.devices[0],source.devices[-1]]
            state=app.request('/api/scan',{});assert state['selected']=='B' and state['resolution']=='1280x720'
            source.devices=[{'id':'Q','name':'No preference','preferred':False},{'id':'P','name':'Second','preferred':False}]
            assert app.request('/api/scan',{})['selected']=='Q'
            source.devices=[];state=app.request('/api/scan',{});assert state['selected'] is None
            _,body=frame(app,status=409);assert json.loads(body)=={'error':'no_device'}
            source.devices=[{'id':'R','name':'Return','preferred':True}]
            assert app.request('/api/scan',{})['selected']=='R'
            valid=source.devices[:];before=app.request('/api/state')
            for devices in [[valid[0],valid[0]],[dict(valid[0],preferred=1)],[dict(valid[0],id='../bad')],
                            [dict(valid[0],name='')],[dict(valid[0],extra=True)],{'id':'R'},[1]]:
                source.devices=devices;app.request('/api/scan',{},status=502);assert app.request('/api/state')==before
            source.devices=valid


def controls_and_display():
    with Source() as source,App(PROJECT,['--camera-port',str(source.port)]) as app,App(PROJECT,['--camera-port',str(source.port)]) as other,sync_playwright() as p:
        for key,button in [('Enter',0),('Equal',4),('Equal',4),('Equal',4),('Minus',5),('Escape',1),('Minus',5),('Minus',5)]:
            left=control(app,'key',key=key);right=control(other,'controller',button=button);assert left==right
        assert left['zoom']==1 and not left['kiosk'] and left['last_action']=='zoom_out'
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page(viewport={'width':1100,'height':850});page.set_default_timeout(5000)
            # Consecutive frames may change valid source geometry, including boundaries.
            for source_width,source_height in [(8,8),(96,72),(320,240),(17,22),(31,19)]:
                source.width,source.height=source_width,source_height
                _,data=frame(app);check_pixels(page,data,source,640,480)
            for zoom in (1,2,4):
                if zoom>1:control(app,'key',key='Equal')
                for source_width,source_height in [(8,8),(96,72),(320,240),(17,22),(31,19)]:
                    source.width,source.height=source_width,source_height
                    _,data=frame(app);check_pixels(page,data,source,640,480,zoom=zoom)
            before=app.request('/api/state');after=control(app,'display',value='auxiliary')
            assert after==dict(before,display_input='auxiliary')
            headers,data=frame(app);assert headers['X-Display-Input']=='auxiliary'
            check_pixels(page,data,source,640,480,zoom=4,input_='auxiliary')
            assert source.requests[-1]=={'op':'frame','input':'auxiliary'}
            control(app,'display',value='preview');control(app,'device',id='SOURCE-B')
            _,data=frame(app);check_pixels(page,data,source,640,480,zoom=4,device='SOURCE-B')
            page.goto(app.url);wait_pixel(page)
            with page.expect_response('**/api/control'):page.keyboard.press('Enter')
            assert page.locator('#controls').is_hidden()
            page.wait_for_function('document.querySelector("#monitor").getBoundingClientRect().height===window.innerHeight')
            old=app.request('/api/state');assert old['kiosk'] is True
            source.frozen=None;wait_live_pixels(page)
            source.frozen=11
            with page.expect_response('**/api/control'):page.keyboard.press('Escape')
            assert page.locator('#controls').is_visible()
            assert app.request('/api/state')==dict(old,kiosk=False,display_input='preview',last_action='back')
            with page.expect_response('**/api/control'):page.locator('[data-button="5"]').click()
            assert app.request('/api/state')['zoom']==2
            with page.expect_response('**/api/control'):page.locator('#display-input').select_option('auxiliary')
            # Verify displayed decoded pixels, not the canvas's own data-input label.
            expected=source.rgb_at((source.width-source.width//2)//2,(source.height-source.height//2)//2,11,'auxiliary')+[255]
            wait_pixel(page,expected)
            actual=page.locator('#video').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(0,0,1,1).data)');assert actual==expected
        finally:browser.close()


def recovery():
    with FaultSource() as source,App(PROJECT,['--camera-port',str(source.port)]) as app,sync_playwright() as p:
        control(app,'resolution',value='1280x720');control(app,'key',key='Equal');control(app,'key',key='Enter');control(app,'display',value='auxiliary')
        before=app.request('/api/state')
        for event in [{'type':'key','key':'Unknown'},{'type':'controller','button':True},{'type':'controller','button':99},
                      {'type':'device','id':'MISSING'},{'type':'display','value':'external'},{'type':'unknown'},
                      {'type':'resolution','value':None}, {'type':'controller','button':[]},{}]:
            app.request('/api/control',event,status=400);assert app.request('/api/state')==before
        app.stop();app.start();state=app.request('/api/state')
        assert state==dict(before,zoom=1,display_input='preview',last_action=None,selected='SOURCE-A')
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();page.set_default_timeout(5000)
            for mode in ['bad-magic','short-header','truncated','wrong-size','zero-width','oversize-width','timeout']:
                source.mode=mode;_,body=frame(app,status=502);assert isinstance(json.loads(body)['error'],str)
                assert app.request('/api/state')==state
                source.mode='good';_,data=frame(app);check_pixels(page,data,source,1280,720)
            page.goto(app.url);wait_pixel(page)
            source.mode='bad-magic';page.wait_for_function("Array.from(document.querySelector('#video').getContext('2d').getImageData(0,0,1,1).data).every(v=>v===0)")
            cleared=page.locator('#video').evaluate('(c)=>{const d=c.getContext("2d").getImageData(0,0,c.width,c.height).data;return d.every(x=>x===0)}');assert cleared,'stale pixels remained after capture failure'
            source.seed=(source.seed+47)%100;source.mode='good';wait_pixel(page,source.rgb_at(0,0,11)+[255])
            actual=page.locator('#video').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(0,0,1,1).data)')
            assert actual==source.rgb_at(0,0,11)+[255]
        finally:browser.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair:control(app,pair[0],**pair[1]),[('resolution',{'value':'1920x1080'}),('display',{'value':'auxiliary'})]))
        state=app.request('/api/state');assert state['resolution']=='1920x1080' and state['display_input']=='auxiliary'


def main():
    try:prepared=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([capture,resolutions,selection,controls_and_display,recovery],1):
        try:test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':prepared,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
