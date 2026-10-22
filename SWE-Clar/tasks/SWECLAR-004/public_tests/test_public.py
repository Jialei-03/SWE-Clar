"""Visible application and profile regression; business policies remain undisclosed."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from network_support import App,login_page
from playwright.sync_api import sync_playwright,expect


def check(app):
    app.request('/api/me',status=401)
    token=app.login();assert app.request('/api/me',token=token)['user']['id']=='u1'
    for path in ['/app.py','/fixtures/demo.json','/network.sqlite']:
        app.request(path,token=token,status=404)
    changed={'interests':['craft','music'],'x':2.5,'y':-1}
    result=app.request('/api/profile',changed,token,method='PUT')['user']
    assert all(result[k]==v for k,v in changed.items())
    app.stop();app.start()
    assert app.request('/api/me',token=token)['user']==result
    assert app.database_probe()['integrity']=='ok'
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();login_page(page,app)
            for width in [375,1280]:
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                for selector in ['#profile button','#discover button','#request','#message-form button','#group-form button','#post-form button','#subscribe button']:
                    expect(page.locator(selector)).to_be_visible()
            page.locator('#interests').fill('books');page.locator('#x').fill('3');page.locator('#y').fill('4');page.locator('#profile button').click()
            expect(page.locator('#feedback')).to_have_text('saved')
            stored=app.request('/api/me',token=token)['user'];assert stored['interests']==['books'] and stored['x']==3 and stored['y']==4
            page.locator('#discover button').click();page.locator('#results [data-user-id]').first.wait_for()
            page.locator('#logout').click();expect(page.locator('#login')).to_be_visible();expect(page.locator('#results')).to_be_empty()
        finally:browser.close()


if __name__=='__main__':
    with App() as app:check(app)
    print('Visible local application passed')
