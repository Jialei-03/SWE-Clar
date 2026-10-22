"""Visible existing page adapter and real PHP/browser baseline."""
import os,sys,json,tempfile,subprocess,select
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests');from browser_isolation import launch
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);root.chmod(0o777);project=os.environ.get('SWECLAR_PROJECT_DIR','/workspace');env={'PATH':os.environ['PATH'],'HOME':'/tmp'}
 worker=subprocess.Popen([sys.executable,'-I','/public_tests/worker.py',project],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
 try:
  assert select.select([worker.stdout],[],[],5)[0];ready=json.loads(worker.stdout.readline());assert ready['uid']==1000 and ready['cap_eff']==0
  action={'type':'upsert_page','page_id':'home','title':'Public sample','body':'Literal <b>text</b>','sections':['One','Two'],'asset_ids':[],'viewport_width':400};worker.stdin.write(json.dumps({'state':{},'action':action,'source_root':'/workspace/runtime/source','output_root':str(root)})+'\n');worker.stdin.flush();assert select.select([worker.stdout],[],[],5)[0];r=json.loads(worker.stdout.readline());assert 'error' not in r['result'] and r['action']==action
  php=subprocess.Popen([sys.executable,'-I','/public_tests/php_launcher.py',project,str(root),str(root/'proof.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
  try:
   assert select.select([php.stdout],[],[],5)[0];url='http://127.0.0.1:'+str(json.loads(php.stdout.readline())['port'])+'/index.php?page=home'
   with sync_playwright() as p:
    browser=launch(p.chromium,headless=True)
    try:
     page=browser.new_page();page.goto(url);assert page.locator('h1').inner_text()=='Public sample';assert page.locator('.intro').inner_text()=='Literal <b>text</b>';assert page.locator('.intro b').count()==0
    finally:browser.close()
  finally:php.terminate();php.wait(timeout=5)
 finally:worker.terminate();worker.wait(timeout=5)
print('PASS: immutable action, real local page data and escaped PHP rendering')
