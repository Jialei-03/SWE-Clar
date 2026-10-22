"""Public foundation regressions for the actual local competitor web app.

Run from /workspace after the benchmark prepares the provider and browser.
These tests cover disclosed directory/authentication contracts, not the unfinished
monitoring, archive or subscription decisions available through clarification.
"""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright


PROVIDER=os.environ.get('WATCH_SERVICE_URL','http://127.0.0.1:38920')


class Foundation(unittest.TestCase):
    def setUp(self):
        self.work=Path.cwd()
        self.temp=tempfile.TemporaryDirectory(prefix='monitor-public-')
        self.root=Path(self.temp.name)
        if os.geteuid()==0:self.root.chmod(0o777)
        self.fixture=self.root/'fixture.json'
        self.db=self.root/'monitor.sqlite'
        self.fixture.write_text(json.dumps({
            'accounts':[{'id':'public-one','name':'Public analyst one','password':'synthetic-pass'},{'id':'public-two','name':'Public analyst two','password':'synthetic-pass'}],
            'competitors':[{'account_id':'public-one','competitor_id':'catalog','name':'Sample catalog','archived':False,'urls':['/pages/demo-page-a']},{'account_id':'public-two','competitor_id':'service','name':'Sample service','archived':False,'urls':['/pages/demo-page-b']}],
            'subscriptions':[{'account_id':'public-one','sequence':0,'plan':'full','status':'active'},{'account_id':'public-two','sequence':0,'plan':'full','status':'active'}]
        }))
        self.fixture.chmod(0o644)
        self.process=None
        self.start()

    def start(self):
        identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
        self.process=subprocess.Popen([sys.executable,'server.py','--port','0','--db',str(self.db),'--fixtures',str(self.fixture),'--provider-url',PROVIDER],cwd=self.work,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        line=self.process.stdout.readline()
        if not line:
            self.fail('Application exited before printing its startup port: '+self.process.stderr.read())
        self.url='http://127.0.0.1:'+str(json.loads(line)['port'])

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:self.process.terminate()
            self.process.wait(timeout=5)
            self.process.stdout.close();self.process.stderr.close()
            self.process=None

    def tearDown(self):
        self.stop();self.temp.cleanup()

    def call(self,path,body=None,token=None):
        headers={}
        if token:headers['Authorization']='Bearer '+token
        if body is not None:headers['Content-Type']='application/json'
        req=Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
        try:response=urlopen(req,timeout=6)
        except HTTPError as error:response=error
        with response:return response.status,json.loads(response.read())

    def login(self,key):
        status,data=self.call('/api/login',{'id':key,'password':'synthetic-pass'})
        self.assertEqual(status,200)
        self.assertTrue({'id','name'}<=set(data['account']))
        self.assertNotIn('password',data['account'])
        self.assertTrue(data['token'])
        return data['token']

    def test_http_directory_authentication_and_restart(self):
        """Actual foundation API behavior, canonical URLs, ownership and persistence."""
        with urlopen(PROVIDER+'/health',timeout=3) as response:
            self.assertTrue(json.loads(response.read())['ready'],'Prepared provider is unavailable; benchmark environment failure.')
        with urlopen(PROVIDER+'/pages/demo-page-a',timeout=3) as response:
            self.assertEqual(response.status,200)
            self.assertTrue(response.read())
        status,health=self.call('/health');self.assertEqual(status,200);self.assertIs(health['ok'],True)
        self.assertEqual(self.call('/api/competitors')[0],401)
        self.assertEqual(self.call('/api/login',{'id':'public-one','password':'wrong'})[0],401)
        token=self.login('public-one');other=self.login('public-two')
        self.assertEqual(self.call('/api/competitor?competitor_id=catalog',token=other)[0],404)
        body={'competitor_id':'added','name':'  Alpha <catalog>  ','urls':[PROVIDER+'/pages/demo-page-b?x=1#fragment']}
        status,data=self.call('/api/competitors',body,token)
        self.assertEqual(status,200);self.assertEqual(data['competitor']['name'],'Alpha <catalog>')
        self.assertEqual(self.call('/api/competitors',body,token)[0],409)
        for urls in [[PROVIDER+'/pages/demo-page-a',PROVIDER+'/pages/demo-page-a#same'],['https://external.invalid/pages/nope'],[PROVIDER+'/health'],[PROVIDER+'/pages/%61']]:
            bad={**body,'competitor_id':'invalid','urls':urls}
            self.assertEqual(self.call('/api/competitors',bad,token)[0],400)
        status,listing=self.call('/api/competitors?q=ALPHA',token=token)
        self.assertEqual(status,200)
        self.assertEqual([row['competitor_id'] for row in listing['competitors']],['added'])
        detail=self.call('/api/competitor?competitor_id=added',token=token)[1]
        saved=detail['urls'][0]
        self.assertEqual(saved['url'],PROVIDER+'/pages/demo-page-b?x=1')
        self.assertIsNone(saved['text']);self.assertIsNone(saved['sha256']);self.assertIsNone(saved['observed_at_ms'])
        self.assertEqual(self.call('/api/logout',{},token)[0],200)
        self.assertEqual(self.call('/api/me',token=token)[0],401)
        self.stop();self.start()
        token=self.login('public-one')
        self.assertEqual(self.call('/api/competitor?competitor_id=added',token=token)[1]['urls'][0]['url_id'],saved['url_id'])

    def test_browser_directory_and_account_switch(self):
        """A browser can sign in, create/select a competitor and leave no old account detail."""
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page(viewport={'width':390,'height':844})
                page.goto(self.url)
                page.locator('#account').fill('public-one');page.locator('#password').fill('synthetic-pass')
                page.locator('#login-form button').click()
                page.locator('[data-competitor-id="catalog"]').wait_for()
                page.locator('#competitor-id').fill('browser-entry')
                page.locator('#competitor-name').fill('Literal <img> label')
                page.locator('#competitor-urls').fill(PROVIDER+'/pages/demo-page-b')
                page.locator('#competitor-save').click()
                page.locator('[data-competitor-id="browser-entry"]').wait_for()
                page.wait_for_function("document.querySelector('#competitor-detail').textContent.includes('Literal <img> label')")
                self.assertEqual(page.locator('#competitor-detail img').count(),0)
                self.assertEqual(page.locator('[data-url-id]').count(),1)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                page.locator('#logout').click()
                self.assertTrue(page.locator('#application').is_hidden())
                page.locator('#account').fill('public-two')
                page.locator('#password').fill('synthetic-pass')
                page.locator('#login-form button').click()
                page.locator('[data-competitor-id="service"]').wait_for()
                self.assertNotIn('Literal <img> label',page.locator('#application').inner_text())
            finally:browser.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
