"""Initial visible workflow smoke check; business choices are clarified with the client."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from practice_support import App,login_page
from playwright.sync_api import sync_playwright,expect

def check(app):
    token=app.login();assert app.request('/me',token=token)=={'id':'user-a'}
    app.request('/goals',{'id':'public-goal','title':'Practice baseline'},token)
    before=app.request('/goals',token=token);assert isinstance(before,list) and any(isinstance(g,dict) and g.get('id')=='public-goal' for g in before)
    app.stop();app.start();assert app.request('/goals',token=token)==before
    for path in ['/server.py','/config.json','/state.sqlite']:app.request(path,status=404)
    with sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();login_page(page,app)
            for tab in ['Audio','Goals','Survey','Results','Subscription']:page.get_by_test_id('tab-'+tab.lower()).click()
            page.get_by_test_id('tab-goals').click();expect(page.get_by_text('Practice baseline',exact=True)).to_be_visible()
        finally:browser.close()

if __name__=='__main__':
    with App() as app:check(app)
    print('Visible workflow passed')
