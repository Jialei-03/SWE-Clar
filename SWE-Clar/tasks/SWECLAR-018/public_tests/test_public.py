import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
import re
from decimal import Decimal
import os
import sys
from pathlib import Path
sys.path.insert(0, '/opt/sweclar')
from harness import App
from playwright.sync_api import sync_playwright


def timestamp_cell(text, milliseconds):
    normalized=re.sub(r"(?<=\d)[,\u00a0\u202f '’](?=\d{3}(?:\D|$))",'',text.strip())
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?)?',normalized,re.I)
    if match:
        scale=1000 if (match[2] or '').lower() in ('s','second','seconds') else 1
        return Decimal(match[1])*scale==milliseconds
    match=re.fullmatch(r'(\d+):(\d{2})(?::(\d{2}))?(\.\d+)?',normalized)
    if match:
        seconds=(int(match[1])*3600+int(match[2])*60+int(match[3])) if match[3] else int(match[1])*60+int(match[2])
        return (Decimal(seconds)+Decimal(match[4] or '0'))*1000==milliseconds
    return False


def sample():
    pixels = [30 if 6 <= x < 10 and 6 <= y < 10 else 220 for y in range(16) for x in range(16)]
    pgm = 'P2\n# Synthetic public calibration image\n16 16\n255\n' + ' '.join(map(str, pixels))
    config = {'phase_ms':1000,'threshold':60,'min_area':4,'max_area':80,'max_gap_ms':300,
              'max_motion_px':3,'max_lighting_delta':20,'max_area_change':0.2,'max_gaze_px':3}
    document = {'capabilities':{'fps':20,'width':16,'height':16},'config':config,
                'frames':[{'t_ms':t,'pgm':pgm,'target':[7.5,7.5]} for t in range(0,2000,250)]}
    return pgm, pixels, document


def run():
    pgm, pixels, document = sample()
    project = Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
    with App(project) as app:
        app.request('/api/report',status=404)
        assert app.request('/api/preview',{'pgm':pgm}) == {'width':16,'height':16,'pixels':pixels}
        for invalid in ['P5 1 1 255 0','P2 1 1 255 -1','P2 1 1 255 0 1','P2 2 2 255 0','P2 1 1 255 256']:
            app.request('/api/preview',{'pgm':invalid},status=400)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page()
                page.goto(app.url)
                page.locator('#preview-file').set_input_files({'name':'frame.pgm','mimeType':'text/plain','buffer':pgm.encode()})
                page.wait_for_function('(pixels)=>{const c=document.querySelector("#frame");return c.width===16&&c.height===16&&Array.from(c.getContext("2d").getImageData(0,0,16,16).data).every((v,i)=>v===(i%4===3?255:pixels[Math.floor(i/4)]));}',arg=pixels)
                observed=page.locator('#frame').evaluate('(canvas)=>Array.from(canvas.getContext("2d").getImageData(0,0,16,16).data)')
                assert observed == [v for pixel in pixels for v in [pixel,pixel,pixel,255]]
                page.locator('#capture-file').set_input_files({'name':'capture.json','mimeType':'application/json','buffer':json.dumps(document).encode()})
                page.locator('#analyze').click()
                page.wait_for_function("document.querySelectorAll('#measurements tr').length === 8")
                report=app.request('/api/report')
                assert len(report['measurements']) == 8
                assert page.locator('#verdict').inner_text() == report['verdict']
                for i,row in enumerate(report['measurements']):
                    assert any(timestamp_cell(text,row['t_ms']) for text in page.locator('#measurements tr').nth(i).locator('td').all_inner_texts()), 'Measurement row omitted its timestamp'
                with page.expect_download() as download:
                    page.locator('#download').click()
                assert json.loads(Path(download.value.path()).read_text()) == report
                assert download.value.suggested_filename == 'measurement.json'
                bad=json.loads(json.dumps(document));bad['frames'][0]['pgm']='invalid'
                app.request('/api/analyze',bad,status=400)
                assert app.request('/api/report') == report
                app.stop();app.start()
                assert app.request('/api/report') == report
                app.request('/not-a-route',status=404)
            finally:
                browser.close()
    with App(project) as isolated:
        isolated.request('/api/report',status=404)
    print('PASS: actual image pixels, browser upload/table/download, parser errors, atomic report preservation, restart and isolation')


if __name__=='__main__':
    run()
