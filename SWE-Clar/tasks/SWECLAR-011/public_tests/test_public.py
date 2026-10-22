"""Public regression tests for the existing authenticated bilingual profile app.
Run from /workspace. Feature-specific business policies are intentionally absent.
"""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
from http.cookiejar import CookieJar
import json,os,socket,subprocess,tempfile,time,unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPCookieProcessor,urlopen
from playwright.sync_api import sync_playwright,expect

IDENTITY={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}


class Foundation(unittest.TestCase):
    def setUp(self):
        self.project=Path.cwd();self.work=tempfile.TemporaryDirectory(prefix='document-public-');self.root=Path(self.work.name);self.root.chmod(0o777)
        self.env={'PATH':os.environ['PATH'],'HOME':str(self.root),'TCPDF_ROOT':os.environ['TCPDF_ROOT'],'DOCUMENT_DATA_DIR':str(self.root)};self.process=None;self.log=None
        initialized=subprocess.run(['php','init.php','--reset'],cwd=self.project,env=self.env,capture_output=True,text=True,timeout=20,**IDENTITY)
        self.assertEqual(initialized.returncode,0,'Application initialization failed: '+initialized.stderr)
        self.client=build_opener(HTTPCookieProcessor(CookieJar()));self.start()

    def start(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}';self.log=open(self.root/'server.log','a+')
        self.process=subprocess.Popen(['php','-S',f'127.0.0.1:{port}','router.php'],cwd=self.project,env=self.env,stdout=self.log,stderr=self.log,**IDENTITY)
        for _ in range(100):
            if self.process.poll() is not None:self.fail('Application server exited; see server startup output.')
            try:
                with urlopen(self.url,timeout=.2) as response:self.assertEqual(response.status,200)
                break
            except OSError:time.sleep(.05)
        else:self.fail('Prepared PHP server did not become ready.')

    def stop(self):
        if self.process:
            if self.process.poll() is None:self.process.terminate()
            self.process.wait(timeout=5);self.process=None
        if self.log:self.log.close();self.log=None

    def tearDown(self):self.stop();self.work.cleanup()

    def call(self,path,method='GET',body=None):
        request=Request(self.url+'/api'+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:response=self.client.open(request,timeout=5)
        except HTTPError as error:response=error
        with response:return response.status,json.loads(response.read())

    def login(self):
        code,result=self.call('/login','POST',{'username':'admin-a','password':'demo-pass'});self.assertEqual(code,200);self.assertEqual(result['user']['id'],'admin-a');self.assertNotIn('password',result['user'])

    def test_public_api_syntax_validation_and_persistence(self):
        for path in self.project.glob('*.php'):
            result=subprocess.run(['php','-l',str(path)],capture_output=True,text=True,timeout=10, env={'PATH':os.environ['PATH'],'HOME':'/tmp'});self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.call('/profiles')[0],401)
        self.assertEqual(self.call('/login','POST',{'username':'admin-a','password':'wrong'})[0],401)
        self.login();profiles=self.call('/profiles')[1]['profiles'];self.assertEqual([x['id'] for x in profiles],sorted(x['id'] for x in profiles));self.assertEqual(len(profiles),2)
        values={k:'Public sample' for k in ['document_id','name','group','contact','reviewer','reference']};values['name']='Équipe تجريبية';values['reference']='SYN-REF-é';self.assertEqual(self.call('/profiles','POST',{'id':'public-added','values':values})[0],201)
        self.assertEqual(self.call('/profiles','POST',{'id':'public-added','values':values})[0],409)
        for bad in ['', ' '*3, 'W'*161, '\nline', '中', '😀', False, 7]:
            invalid=dict(values,name=bad);self.assertEqual(self.call('/profiles/public-added','PUT',{'values':invalid})[0],400,f'Invalid public profile value was accepted: {bad!r}')
        values['group']='W'*160;self.assertEqual(self.call('/profiles/public-added','PUT',{'values':values})[0],200)
        self.stop();self.start();self.assertEqual(self.call('/session')[1]['user']['id'],'admin-a')
        stored=next(x for x in self.call('/profiles')[1]['profiles'] if x['id']=='public-added');self.assertEqual(stored['values'],values)
        self.assertEqual(self.call('/logout','POST',{})[0],200);self.assertEqual(self.call('/profiles')[0],401)

    def test_browser_existing_profile_edit_and_reload(self):
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(self.url);page.get_by_label('Username',exact=True).fill('editor-a');page.get_by_label('Password',exact=True).fill('demo-pass');page.get_by_role('button',name='Sign in',exact=True).click()
                expect(page.get_by_label('Saved profile',exact=True)).to_be_visible();page.get_by_label('Saved profile',exact=True).select_option('sample-one')
                page.get_by_label('Full name',exact=True).fill('Public browser revision');page.get_by_role('button',name='Save profile',exact=True).click();expect(page.get_by_role('status')).to_contain_text('Profile saved')
                page.reload();expect(page.get_by_label('Full name',exact=True)).to_have_value('Public browser revision')
                page.get_by_role('button',name='Log out',exact=True).click();expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_visible()
            finally:browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
