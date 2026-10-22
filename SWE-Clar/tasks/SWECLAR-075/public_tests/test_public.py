"""Visible regression for the existing account/session and browser shell."""
import os,sys,json,tempfile,subprocess,select
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/public_tests')
from browser_isolation import launch
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);root.chmod(0o777);clock=root/'clock';clock.write_text('1000')
 process=subprocess.Popen([sys.executable,'-I','/public_tests/server_launcher.py',os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),'/workspace/runtime/config.json',str(root/'data.sqlite'),str(clock),str(root/'proof.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
 try:
  assert select.select([process.stdout],[],[],5)[0];url='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
  with sync_playwright() as p:
   browser=launch(p.chromium,headless=True)
   try:
    page=browser.new_page();page.goto(url);page.locator('#email').fill('public@example.test');page.locator('#password').fill('synthetic-pass')
    with page.expect_response(lambda r:r.url.endswith('/register') and r.request.method=='POST') as pending:page.locator('#register').click()
    assert 200<=pending.value.status<300;pending.value.finished()
    page.get_by_role('button',name='Sign in',exact=True).click();page.locator('#workspace').wait_for(state='visible');assert page.context.cookies()[0]['httpOnly'];assert page.locator('#nav button').count()==5;page.reload();page.locator('#workspace').wait_for(state='visible');page.locator('#logout').click();page.locator('#auth').wait_for(state='visible')
   finally:browser.close()
 finally:process.terminate();process.wait(timeout=5)
print('PASS: existing account registration, session reload, revocation and browser shell')
