import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import os
import sys
from pathlib import Path
sys.path.insert(0, '/opt/sweclar')
from harness import App
from playwright.sync_api import sync_playwright


def run():
    project = Path(os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))
    with App(project) as app:
        with sync_playwright() as p:
            browser = _isolated_browser_launch(p.chromium, headless=True)
            try:
                page = browser.new_page()
                page.goto(app.url)
                page.locator('#file').set_input_files({'name':'synthetic.csv','mimeType':'text/csv','buffer':b'account_id,balance_cents,age_days\nPUBLIC-A,10000,20\nPUBLIC-B,20000,75\n'})
                page.get_by_role('button', name='Import CSV', exact=True).click()
                page.get_by_role('button', name='PUBLIC-A', exact=True).wait_for()
                page.get_by_role('button', name='PUBLIC-B', exact=True).click()
                page.locator('#detail h3').wait_for()
                assert page.locator('#detail h3').inner_text() == 'PUBLIC-B'
                rows = app.request('/api/accounts')['accounts']
                assert [r['account_id'] for r in rows] == ['PUBLIC-A','PUBLIC-B']
                assert all(r['status']=='open' and r['note']=='' for r in rows)
                app.request('/api/accounts/UNKNOWN', status=404)
                app.stop()
                app.start()
                assert app.request('/api/accounts')['accounts'] == rows
            finally:
                browser.close()
    print('PASS: CSV upload, browser list/detail, documented defaults, HTTP errors and restart persistence')


if __name__ == '__main__':
    run()
