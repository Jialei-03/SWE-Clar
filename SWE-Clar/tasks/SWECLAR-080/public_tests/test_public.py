"""Visible regression: real WordPress pages, registered component assets and controls."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests');from browser_isolation import launch
url=json.loads(Path('/workspace/runtime/ready.json').read_text())['url']
with sync_playwright() as p:
 browser=launch(p.chromium,headless=True)
 try:
  page=browser.new_page();page.goto(url+'/?directory_page=members');page.get_by_role('heading',name='Member directory').wait_for();assert page.locator('#members article').count()==3;page.locator('#filter').fill('Alpha');page.get_by_role('button',name='Filter',exact=True).click();page.wait_for_function("document.querySelector('#filter-status').textContent==='1 matching members'");page.goto(url+'/?directory_page=about');page.get_by_role('heading',name='About this directory').wait_for()
 finally:browser.close()
print('PASS: real WordPress/MariaDB pages and the existing member filter')
