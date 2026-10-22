"""Visible role scope, prepared reader and pending attendance regressions."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from attendance_support import Application,browser_session,request
from playwright.sync_api import expect


def login(page,app,user):
    page.goto(app.url);page.locator('#username').fill(user['username']);page.locator('#password').fill(user['password']);page.locator('#login').click()
    expect(page.locator('#workspace')).to_be_visible()


def run():
    with Application() as app,browser_session() as browser:
        teacher=next(u for u in app.seed['users'] if u['id']=='teacher-a');parent=next(u for u in app.seed['users'] if u['id']=='parent-a')
        page=browser.new_page(viewport={'width':390,'height':844});login(page,app,teacher)
        expect(page.locator('#roster [data-student-id]')).to_have_count(1)
        expect(page.locator('#roster')).to_contain_text(next(s['name'] for s in app.seed['students'] if s['id']=='student-a'))
        page.locator('#tag-uid').fill('tag-a');page.locator('#device-id').select_option('desk-a');page.locator('#reading-time').fill('120')
        page.locator('#interaction').select_option('proximity');page.locator('#scan').click()
        expect(page.locator('#error')).to_contain_text('intentional_tap_required');expect(page.locator('[data-scan-id]')).to_have_count(0)
        page.locator('#interaction').select_option('tap');page.locator('#scan').click();expect(page.locator('[data-scan-id]')).to_have_count(1)
        expect(page.locator('[data-attendance-id]')).to_have_count(0)
        page.locator('[data-recipient]').select_option('guardian-a');expect(page.locator('[data-attendance-id]')).to_have_count(0)
        assert page.locator('[data-confirm]').is_visible()
        for width,height in [(390,844),(1280,900)]:
            page.set_viewport_size({'width':width,'height':height});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('#logout').click();expect(page.locator('#workspace')).to_be_hidden();page.reload();expect(page.locator('#workspace')).to_be_hidden()
        login(page,app,parent);expect(page.locator('#roster [data-student-id]')).to_have_count(1)
        expect(page.locator('#scan-panel')).to_be_hidden()
        # No attendance was confirmed, so the inbox is legitimately empty.
        # A zero-height empty ul is not a hidden parent-inbox interface.
        expect(page.locator('#inbox-section')).to_be_visible()
        expect(page.locator('#inbox')).to_be_attached()
        expect(page.locator('#inbox').locator('li')).to_have_count(0)
        token=request(app,'/api/login',{'username':teacher['username'],'password':teacher['password']})['body']['token']
        scans=request(app,'/api/scans',token=token)['body']['scans'];assert len(scans)==1 and scans[0]['state']=='pending' and scans[0]['at']==120
        replay=request(app,'/api/scans',{'reading_id':scans[0]['reading_id'],'direction':'in'},token=token)
        assert replay['status']==200 and replay['body']['scan']['id']==scans[0]['id']
        app.stop();app.start()
        token=request(app,'/api/login',{'username':teacher['username'],'password':teacher['password']})['body']['token']
        rows=request(app,'/api/scans',token=token)['body']['scans'];assert len(rows)==1 and rows[0]['id']==scans[0]['id']
    return {'passed':True,'scope':'Visible authenticated roster and deliberate pending simulated readings only'}

if __name__=='__main__':print(json.dumps(run()))
