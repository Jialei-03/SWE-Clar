import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import base64
import os
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError,URLError
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,'/public_tests')
from harness import App,CandidateFailure
from preflight import preflight
from source_support import Source
from playwright.sync_api import sync_playwright
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def control(app,kind,**fields):return app.request('/api/control',dict(type=kind,**fields))
def frame(app,status=200):
    try:r=urlopen(app.url+'/api/frame',timeout=8)
    except HTTPError as error:r=error
    except (URLError,ConnectionError,TimeoutError) as error:raise CandidateFailure(str(error)) from error
    with r:
        data=r.read();assert r.status==status,(r.status,data[:100])
        return dict(r.headers),data
def decode(page,data,points):
    assert data.startswith(b'\x89PNG\r\n\x1a\n'),'not PNG'
    return page.evaluate('''async ({b64,points})=>{
      const image=await createImageBitmap(await (await fetch('data:image/png;base64,'+b64)).blob());
      const c=document.createElement('canvas');c.width=image.width;c.height=image.height;
      const ctx=c.getContext('2d');ctx.drawImage(image,0,0);image.close();
      return {width:c.width,height:c.height,pixels:points.map(([x,y])=>Array.from(ctx.getImageData(x,y,1,1).data))};
    }''',{'b64':base64.b64encode(data).decode(),'points':points})
def check_pixels(page,data,source,width,height,zoom=1,input_='preview',device='SOURCE-A',sequence=11):
    points=[(0,0),(width-1,0),(0,height-1),(width-1,height-1),(width//2,height//2),(width//3,height//5)]
    decoded=decode(page,data,points);assert (decoded['width'],decoded['height'])==(width,height)
    cw,ch=source.width//zoom,source.height//zoom;left,top=(source.width-cw)//2,(source.height-ch)//2
    expected=[source.rgb_at(left+x*cw//width,top+y*ch//height,sequence,input_,device)+[255] for x,y in points]
    assert decoded['pixels']==expected,(decoded['pixels'],expected)

def wait_pixel(page,expected=None):
    page.wait_for_function('''expected=>{
      const c=document.querySelector('#video');if(!c||!c.width||!c.height)return false;
      const p=Array.from(c.getContext('2d').getImageData(0,0,1,1).data);
      return expected ? p.every((v,i)=>v===expected[i]) : p[3]===255;
    }''',arg=expected)

def wait_live_pixels(page):
    wait_pixel(page)
    for _ in range(3):
        old=page.locator('#video').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(0,0,1,1).data)')
        page.wait_for_function('''old=>{const p=document.querySelector('#video').getContext('2d').getImageData(0,0,1,1).data;return p[3]===255&&old.some((v,i)=>v!==p[i]);}''',arg=old)


def capture():
    with Source() as source,App(PROJECT,['--camera-port',str(source.port)]) as app,sync_playwright() as p:
        assert app.request('/api/state')['devices']==source.devices
        control(app,'device',id='SOURCE-B')
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();page.set_default_timeout(5000)
            headers,data=frame(app);assert headers['X-Frame-Sequence']=='11'
            check_pixels(page,data,source,640,480,device='SOURCE-B')
            assert source.requests[-1]=={'op':'frame','input':'preview','device_id':'SOURCE-B'}
            source.frozen=None;page.goto(app.url)
            wait_live_pixels(page)
            values=page.locator('#video').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(100,100,1,1).data)')
            assert values[3]==255 and any(values[:3])
        finally:browser.close()
    # The released default source is also usable without manual peripheral setup.
    with App(PROJECT) as app:
        assert len(app.request('/api/state')['devices'])==2
        _,data=frame(app);assert data.startswith(b'\x89PNG')


def resolutions():
    with Source() as source,App(PROJECT,['--camera-port',str(source.port)]) as app,sync_playwright() as p:
        control(app,'device',id='SOURCE-A');browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();page.set_default_timeout(5000)
            for width,height in [(640,480),(1280,720),(1920,1080)]:
                state=control(app,'resolution',value=f'{width}x{height}')
                _,data=frame(app);check_pixels(page,data,source,width,height)
                assert state['selected']=='SOURCE-A' and state['zoom']==1
            before=app.request('/api/state')
            assert app.request('/api/control',{'type':'resolution','value':'800x600'},status=400)=={'error':'invalid_resolution'}
            assert app.request('/api/state')==before
            page.goto(app.url);page.wait_for_function("document.querySelector('#video').width===1920")
            with page.expect_response('**/api/control'):page.locator('#resolution').select_option('1280x720')
            page.wait_for_function("document.querySelector('#video').width===1280&&document.querySelector('#video').height===720")
        finally:browser.close()


def run():capture();resolutions();print('Public actual capture and resolution checks passed')
if __name__=='__main__':preflight();run()
