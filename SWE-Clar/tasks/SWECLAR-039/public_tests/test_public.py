import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import os
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,str(Path(__file__).resolve().parent))
from harness import App
from peer_support import Peer
from playwright.sync_api import sync_playwright


def run():
    project=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
    with Peer() as peer,App(project,['--peer-port',str(peer.port)]) as app:
        assert app.request('/api/state')=={'devices':[],'paired':[],'connected':None,'commands':[],'telemetry':[]}
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page(viewport={'width':1024,'height':900});page.goto(app.url)
                page.locator('#scan').click();page.locator('[data-device="PUBLIC-A"]').wait_for()
                buttons=page.locator('#device-list button')
                assert buttons.count()==1 and buttons.first.get_attribute('data-device')=='PUBLIC-A'
                assert 'Updated <sensor> A' in buttons.first.inner_text()
                assert page.locator('#device-list sensor').count()==0
                page.locator('[data-device="PUBLIC-A"]').click();assert page.locator('#device').input_value()=='PUBLIC-A'
                assert page.locator('#pair-code').get_attribute('type')=='password'
                assert peer.requests==[{'op':'scan','service':'capture.v1'}]
                assert app.request('/api/state')['devices']==[{'device_id':'PUBLIC-A','name':'Updated <sensor> A','services':['capture.v1']}]
            finally:browser.close()
        app.request('/api/scan',{'service':True},status=400);assert len(peer.requests)==1
        app.request('/missing',status=404)
    with App(project) as app:
        devices=app.request('/api/scan',{'service':'capture.v1'})['devices']
        assert [d['device_id'] for d in devices]==['SENSOR-A','SENSOR-B']
        children=Path(f'/proc/{app.process.pid}/task/{app.process.pid}/children').read_text().split()
        assert len(children)==1 and b'peer.py' in (Path('/proc')/children[0]/'cmdline').read_bytes()
        app.stop();assert not (Path('/proc')/children[0]).exists()
    print('PASS: independently framed discovery, latest advertisement rendering, safe text, public controls, runnable peer and child cleanup')


if __name__=='__main__':run()
