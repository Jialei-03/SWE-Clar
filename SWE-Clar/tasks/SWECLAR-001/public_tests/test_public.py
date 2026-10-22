"""Visible application contract only; hidden client choices are not asserted."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from listing_support import Workspace,draft
from playwright.sync_api import sync_playwright,expect


def public_contract():
    with Workspace() as work:
        saved=work.request('/api/listings',draft(),status=201)['listing']
        assert saved['state']=='draft' and saved['floor_area']==100
        work.request('/api/listings/'+saved['id'],{'asking_price':True},method='PUT',status=400)
        assert work.request('/api/listings/'+saved['id'])['listing']==saved
        work.restart();assert work.request('/api/listings/'+saved['id'])['listing']==saved
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page()
                page.goto(work.app.url)
                page.locator('#listings [data-id="parcel-a"]').click()
                expect(page.locator('#draft-form [name="label"]')).to_have_value('Synthetic Parcel A')
                page.locator('#draft-form [name="label"]').fill('Synthetic public browser parcel')
                page.locator('#draft-form button').click()
                expect(page.locator('#title')).to_have_text('Synthetic public browser parcel')
                page.locator('#comparables').fill('[]');page.locator('#count').select_option('2');page.locator('#analyze').click()
                expect(page.locator('#analysis')).to_contain_text('Synthetic public browser parcel')
                expect(page.locator('#analysis')).to_contain_text('courtyard')
            finally:browser.close()
    return {'public_passed':True}


if __name__=='__main__':
    print(json.dumps(public_contract()))
