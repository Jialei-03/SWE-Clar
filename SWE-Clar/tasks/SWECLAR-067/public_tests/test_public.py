"""Visible baseline: real controls, literal text and immutable snapshots/events."""
import json,os,select,subprocess,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests')
from browser_isolation import launch
process=subprocess.Popen([sys.executable,'-I','/public_tests/serve.py','--project',os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),'--port','0'],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
 assert select.select([process.stdout],[],[],5)[0];ready=json.loads(process.stdout.readline());assert ready['uid']==1000 and ready['cap_eff']==0
 with sync_playwright() as p:
  browser=launch(p.chromium,headless=True)
  try:
   page=browser.new_page();page.goto('http://127.0.0.1:'+str(ready['port']));page.get_by_role('heading',name='Pick up where you left off').wait_for()
   assert page.evaluate('''async()=>{const e={type:'show_page',page:'clinic'},before=JSON.stringify(e);await window.assistantApp.dispatch(e);const copy=window.assistantApp.snapshot();copy.routes.chat='changed';return JSON.stringify(e)===before&&window.assistantApp.snapshot().routes.chat!=='changed'}''')
   assert page.locator('#clinic').is_visible();page.get_by_role('button',name='Home',exact=True).click();assert page.locator('#home').is_visible()
  finally:browser.close()
finally:process.terminate();process.wait(timeout=5)
print('PASS: existing navigation controls and independent snapshots/events')
