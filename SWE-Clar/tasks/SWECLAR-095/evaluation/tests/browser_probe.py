from playwright.sync_api import sync_playwright
import sys,time
sys.path.insert(0,'/public_tests')
from browser_isolation import launch

def probe(url,mode):
 with sync_playwright() as pw:
  browser=launch(pw.chromium,headless=True)
  try:
   page=browser.new_page(viewport={'width':1024,'height':900});page.set_default_timeout(7000);r={'errors':[]};page.on('pageerror',lambda e:r['errors'].append(str(e)));button=lambda s:page.get_by_role('button',name=s,exact=True)
   page.goto(url);page.get_by_label('Email',exact=True).fill('browser@example.test');page.get_by_label('Password',exact=True).fill('synthetic-passphrase');button('Sign in').click();button('Sign out').wait_for();r['login']=True
   if mode=='catalog':
    page.get_by_label('Search',exact=True).fill('OTHER');button('Search catalog').click();page.wait_for_function("document.querySelectorAll('li').length===1");r['search']=page.locator('li h3').all_text_contents()==['Blue tone'];page.get_by_label('Search',exact=True).fill('');button('Search catalog').click();page.wait_for_function("document.querySelectorAll('li').length===2")
    r['layout']=True
    for width in [360,1024]:
     page.set_viewport_size({'width':width,'height':900});r['layout'] &= page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     for b in page.get_by_role('button').all():
      if b.is_visible():
       box=b.bounding_box();r['layout'] &= box['x']>=0 and box['x']+box['width']<=width
   if mode=='playback':
    page.evaluate('window.syntheticReloadGuard=7');page.get_by_label('Local transaction').fill('browser-credit');button('Confirm purchase').click();page.get_by_text('Tokens: 9',exact=True).wait_for();page.get_by_test_id('unlock-tone').click();page.get_by_text('Tokens: 6',exact=True).wait_for();r['balance']=page.evaluate('window.syntheticReloadGuard===7')
    page.route('**/media/tone',lambda route:(time.sleep(.35),route.continue_()))
    with page.expect_request('**/media/tone'):page.get_by_test_id('play-tone').click()
    r['loading']=page.get_by_role('status').text_content()=='Loading';page.wait_for_function("document.querySelector('audio')?.currentTime>.3");page.unroute('**/media/tone');audio=page.locator('audio');r['audio']=audio.evaluate('a=>a.readyState>=2&&!a.paused');button('Pause').click();at=audio.evaluate('a=>a.currentTime');page.wait_for_timeout(250);r['pause']=audio.evaluate('(a,t)=>a.paused&&Math.abs(a.currentTime-t)<.05',at);button('Resume').click();page.wait_for_function("document.querySelector('audio').currentTime>"+str(at+.2));r['resume']=True;button('Pause').click();before=audio.evaluate('a=>a.currentTime');audio.evaluate('a=>a.currentTime=0');page.wait_for_timeout(150);r['noRewind']=audio.evaluate('(a,t)=>a.currentTime>=t-.15',before)
   button('Sign out').click();button('Sign in').wait_for();r['logout']=page.locator('audio').evaluate("a=>a.paused&&!a.getAttribute('src')")
   return r
  finally:browser.close()
