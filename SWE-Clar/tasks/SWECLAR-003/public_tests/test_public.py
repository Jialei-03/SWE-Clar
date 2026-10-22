"""Visible real-build and responsive-page checks; no hidden business policies."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from campaign_support import Site
from playwright.sync_api import sync_playwright,expect

def visible_build(site):
    one,result=site.build(site.spec);assert result=={'index_file':'index.html'}
    two,result=site.build(site.spec,cli=True);assert result=={'index_file':'index.html'}
    assert site.files(one)==site.files(two),'Function/CLI builds must be deterministic'
    return one

def visible_layout(page,count,width):
    page.set_viewport_size({'width':width,'height':1000})
    for ident in ['hero','campaigns','contact','footer']:expect(page.locator('#'+ident)).to_be_visible()
    cards=page.locator('.campaign-card');expect(cards).to_have_count(count);boxes=[p.bounding_box() for p in cards.all()];assert all(boxes)
    columns=3 if width>=1024 else 2 if width>=600 else 1
    assert sum(abs(b['y']-boxes[0]['y'])<2 for b in boxes)==min(columns,count)
    for i,b in enumerate(boxes):
        row=(i//columns)*columns;assert abs(b['y']-boxes[row]['y'])<2
        if row:assert b['y']>=max(prev['y']+prev['height'] for prev in boxes[row-columns:row])-1
    assert all(b['width']>0 and b['x']>=-1 and b['x']+b['width']<=width+1 for b in boxes)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')

if __name__=='__main__':
    with Site() as site:
        out=visible_build(site)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(site.serve(out))
                for width in [375,800,1280]:visible_layout(page,len(site.spec['campaigns']),width)
            finally:browser.close()
    print('Visible build and layout passed')
