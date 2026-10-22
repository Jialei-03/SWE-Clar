"""Public session, profile and relationship regression through actual HTTP/browser/storage."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from public_support import application,request,database_rows
from playwright.sync_api import sync_playwright,expect

def fixture():
 return {'clock_ms':1704196800000,'users':[{'id':u,'name':name,'role':role,'bio':'Synthetic public profile','password':'public-pass'} for u,name,role in [('company-a','Public company A','employer'),('company-b','Public company B','employer'),('worker-a','Public worker A','employee'),('worker-b','Public worker B','employee')]],'jobs':[],'relationships':[],'resumes':[],'applications':[],'interviews':[],'views':[]}

def main():
 f=fixture()
 with application(f) as app:
  request(app,'/api/login',body={'id':'worker-a','password':'wrong'},method='POST',status=401)
  token=request(app,'/api/login',body={'id':'worker-a','password':'public-pass'},method='POST')['token']
  request(app,'/api/me','forged',status=401)
  users=request(app,'/api/profiles',token)['profiles'];assert [u['id'] for u in users]==['company-a','company-b','worker-a','worker-b'];assert all(set(['password','password_hash']).isdisjoint(u) for u in users)
  for target,kind in [('company-a','follow'),('worker-b','connect')]:
   body={'target_id':target,'kind':kind,'enabled':True};request(app,'/api/relationships',token,body,'POST');request(app,'/api/relationships',token,body,'POST')
  assert len(database_rows(app,'relationships'))==2
  request(app,'/api/relationships',token,{'target_id':'worker-b','kind':'follow','enabled':True},'POST',status=403)
  literal='Public <img src=x onerror=alert(1)> profile'
  with sync_playwright() as p:
   browser=_isolated_browser_launch(p.chromium, headless=True);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   try:
    page.goto(app.url);page.locator('#account').fill('worker-a');page.locator('#password').fill('public-pass');page.locator('#login-form button').click();expect(page.locator('[data-profile-id]')).to_have_count(4)
    page.locator('#profile-name').fill(literal);page.locator('#profile-bio').fill('Literal <b>biography</b>');page.locator('#profile-save').click();expect(page.locator('[data-profile-id="worker-a"]')).to_contain_text(literal);assert page.locator('#profiles img,#profiles b').count()==0
    page.locator('#relation-target').select_option('worker-b');page.locator('#relation-kind').select_option('connect');page.locator('#relation-enabled').uncheck();page.locator('#relationship-save').click();expect(page.locator('#relationships')).not_to_contain_text('worker-b')
    for width,height in [(390,844),(1280,900)]:page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden();assert page.locator('#profiles').inner_text()=='';assert not errors,errors
   finally:browser.close()
  assert request(app,'/api/me',token)['user']['name']==literal
  app.stop();app.start();assert request(app,'/api/me',token)['user']['name']==literal;assert len(database_rows(app,'relationships'))==1
  request(app,'/api/logout',token,{},'POST');request(app,'/api/me',token,status=401)
 print(json.dumps({'passed':True,'checks':['actual_login','profile_literal_render','role_relationships','database_rows','restart_persistence','viewports','logout_clear']}))
if __name__=='__main__':main()
