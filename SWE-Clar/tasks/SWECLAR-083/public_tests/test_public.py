import subprocess,sys,os,tempfile,json,select,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests');from browser_isolation import launch
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);root.chmod(0o777)
 p=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',str(Path.cwd()),'http://127.0.0.1:23083/network',str(root/'state.json'),str(root/'proof.json')],env={'PATH':os.environ['PATH'],'HOME':'/tmp'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  assert select.select([p.stdout],[],[],5)[0];url='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
  with sync_playwright() as pw:
   browser=launch(pw.chromium,headless=True)
   try:
    page=browser.new_page();page.goto(url);assert page.get_by_role('heading',name='Local route planner').is_visible();assert page.locator('#map').count()==1
   finally:browser.close()
 finally:p.terminate();p.wait(timeout=5)
print('Public navigation shell passed')
