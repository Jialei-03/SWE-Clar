"""Public regression: existing server, cookies, local provider and Leaflet UI."""
import json,os,subprocess,sys,select,tempfile,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests')
from browser_isolation import launch
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);root.chmod(0o777)
 cfg=Path('/workspace/runtime/roof-config.json')
 process=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),str(cfg),str(root/'roof.sqlite'),str(root/'proof.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
 try:
  assert select.select([process.stdout],[],[],5)[0];url='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
  with sync_playwright() as p:
   browser=launch(p.chromium,headless=True)
   try:
    page=browser.new_page();page.goto(url);page.get_by_role('heading',name='Roof estimate').wait_for();page.locator('[name=roof_type] option').first.wait_for(state='attached');assert page.evaluate('typeof L.map')=='function';assert page.locator('#detected').is_hidden()
    cookies=page.context.cookies();assert cookies and cookies[0]['httpOnly']
   finally:browser.close()
 finally:process.terminate();process.wait(timeout=5)
print('PASS: existing HTTP entry point, local Leaflet and isolated cookie session')
