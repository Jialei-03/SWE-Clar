"""Visible journal and date-correction regression in the prepared browser."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from pathlib import Path
import datetime,sys,json
sys.path.insert(0,str(Path(__file__).parent))
from cycle_support import Site,open_page,create,plan
from playwright.sync_api import sync_playwright,expect

with Site() as site,sync_playwright() as p:
    browser=_isolated_browser_launch(p.chromium, channel='chromium', headless=True)
    try:
        context=browser.new_context(permissions=['notifications'],timezone_id='UTC');page=context.new_page();page.clock.install(time=datetime.datetime(2028,2,29,7,59,tzinfo=datetime.timezone.utc));open_page(page,site)
        ident=create(page);expect(page.locator('#current-day')).to_have_text('1');expect(page.locator('#today')).to_have_text('2028-02-29')
        for width in [375,1280]:
            page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            expect(page.locator('#settings-form button')).to_be_visible();expect(page.locator('#enable-notifications')).to_be_visible()
        page.locator('#period-start').fill('2028-02-25');page.locator('#settings-form button').click();expect(page.locator('#feedback')).to_have_text('saved')
        expect(page.locator('#current-day')).to_have_text('5');assert page.locator('#timeline [data-date]').count()==28
        before=page.locator('#timeline').inner_text();page.reload();page.wait_for_function('navigator.serviceWorker.controller!==null');expect(page.locator('#period-start')).to_have_value('2028-02-25');assert page.locator('#timeline').inner_text()==before
        second=create(page,'Second journal');assert second!=ident;expect(page.locator('#current-day')).to_have_text('1')
        page.locator('#profile-select').select_option(ident);expect(page.locator('#period-start')).to_have_value('2028-02-25');expect(page.locator('#current-day')).to_have_text('5')
        inputs={'periodStart':'2028-02-25','cycleLength':28,'periodLength':5,'asOf':'2028-02-29'};out=plan(page,inputs);assert out['immutable'] and out['result']==plan(page,inputs)['result']
        print('Visible local journal passed')
    finally:browser.close()
