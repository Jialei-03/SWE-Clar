"""Visible ingestion, access, persistence and live browser regressions."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json,re,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from public_support import application,request,database_rows
from playwright.sync_api import sync_playwright,expect


def fixture():
    return {'clock_ms':1704196800000,'feed_token':'public-feed','households':[{'id':h,'name':h.title(),'freshness_minutes':10,'night_start':1320,'night_end':360,'sleep_start':1380,'sleep_end':420} for h in ['north','south']], 'users':[{'id':'member','name':'Public member','role':'individual','household_id':'north','assignments':[],'password':'public-password'},{'id':'helper','name':'Public helper','role':'caregiver','household_id':None,'assignments':['north','south'],'password':'public-password'}], 'rooms':[{'household_id':h,'id':'room','name':h+' room'} for h in ['north','south']], 'sensors':[{'household_id':h,'id':'switch','room_id':'room','name':h+' sensor','kind':'presence'} for h in ['north','south']], 'events':[{'household_id':'north','event_id':'a','sensor_id':'switch','timestamp_ms':1704196800000,'value':False}], 'rules':[]}


def main():
    f=fixture();now=f['clock_ms']
    with application(f) as app:
        login=request(app,'/api/login',body={'id':'member','password':'public-password'},method='POST');token=login['token']
        assert {k:login['user'][k] for k in ['id','name','role']}=={'id':'member','name':'Public member','role':'individual'}
        assert [h['id'] for h in request(app,'/api/homes',token)['households']]==['north']
        request(app,f'/api/snapshot?household_id=south&as_of={now}',token,status=403)
        event={'household_id':'north','event_id':'b','sensor_id':'switch','timestamp_ms':now,'value':True}
        request(app,'/api/ingest',token,event,'POST',status=401)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True);page=browser.new_page(viewport={'width':390,'height':844});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(app.url);page.locator('#account').fill('member');page.locator('#password').fill('public-password');page.locator('#login-form button').click()
                expect(page.locator('[data-sensor-id="switch"] .state')).to_have_text(re.compile('off',re.I))
                result=request(app,'/api/ingest','public-feed',event,'POST');assert result['accepted'] is True and result['duplicate'] is False
                expect(page.locator('[data-sensor-id="switch"] .state')).to_have_text(re.compile('on',re.I),timeout=5000)
                assert request(app,'/api/ingest','public-feed',event,'POST')['duplicate'] is True
                request(app,'/api/ingest','public-feed',{**event,'value':False},'POST',status=409)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.set_viewport_size({'width':1280,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#logout').click();expect(page.locator('#application')).to_be_hidden();assert page.locator('#rooms').inner_text()==''
                assert not errors,errors
            finally:browser.close()
        assert len(database_rows(app,'events'))==2
        app.stop();app.start()
        rows=request(app,f'/api/snapshot?household_id=north&as_of={now}',token)['rooms'];assert rows[0]['sensors'][0]['value'] is True
        request(app,'/api/logout',token,{},'POST');request(app,'/api/me',token,status=401)
    print(json.dumps({'passed':True,'checks':['real_authorized_http','atomic_replay','live_browser_polling','two_viewports','logout_clear','database_reopen']}))


if __name__=='__main__':main()
