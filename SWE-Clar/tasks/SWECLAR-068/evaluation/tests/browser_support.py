from pathlib import Path
import os,json,sys,subprocess,select,tempfile,secrets
from contextlib import contextmanager
from playwright.sync_api import sync_playwright
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();WHITE_PATH='/usr/local/bin:/usr/bin:/bin'
os.environ['SIGNAL_PRIVATE_SENTINEL']=secrets.token_hex(24)
def identity(pid):
 fields=dict(x.split(':',1) for x in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in x);assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
class App:
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.path.chmod(0o777)
  self.process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':WHITE_PATH,'HOME':'/tmp','PORT':'0','PYTHONDONTWRITEBYTECODE':'1'})
  assert select.select([self.process.stdout],[],[],8)[0];self.url='http://127.0.0.1:'+str(json.loads(self.process.stdout.readline())['port']);identity(self.process.pid)
  self.playwright=sync_playwright().start();proof=self.path/'browser.json'
  self.browser=self.playwright.chromium.launch(headless=True,executable_path='/public_tests/browser_launcher.py',downloads_path=str(self.path),env={'PATH':WHITE_PATH,'HOME':'/tmp','CLARSWE_BROWSER_BINARY':self.playwright.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  info=json.loads(proof.read_text());identity(info['pid']);assert info['uid']==1000 and info['cap_eff']==0 and 'SIGNAL_PRIVATE_SENTINEL' not in info['environment_keys'];return self
 def __exit__(self,*args):
  self.browser.close();self.playwright.stop();self.process.terminate();self.process.wait(timeout=5);self.tmp.cleanup()
 @contextmanager
 def page(self,width=390):
  context=self.browser.new_context(viewport={'width':width,'height':800});page=context.new_page();page.set_default_timeout(5000)
  try:page.goto(self.url);yield page
  finally:context.close()
