import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import json
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar')
from harness import App
from preflight import preflight
from playwright.sync_api import sync_playwright
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def action(app,kind,**fields): return app.request('/api/action',dict(type=kind,**fields))
def stored(app):
    with sqlite3.connect(app.db) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]>0
    document=app.request('/api/document')
    return {'state':app.request('/api/state'),'document':document['nodes'],'current':document['current']}


def host_and_bookmarks():
    with App(PROJECT) as app, sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page(viewport={'width':1200,'height':850});page.set_default_timeout(5000);page.goto(app.url)
            page.locator('[data-paragraph="PAR-A"]').wait_for()
            for kind in ['notebook','group','section','page','paragraph']:
                page.locator('#target-kind').select_option(kind)
                with page.expect_response('**/api/action'):page.locator('#add-bookmark').click()
                assert page.locator('#sidebar').is_visible()
            items=app.request('/api/state')['tabs'][0]['items']
            assert [x['target_type'] for x in items]==['notebook','group','section','page','paragraph']
            assert [x['target_id'] for x in items]==['BOOK-A','GROUP-A','SECTION-A','PAGE-A','PAR-A']
            assert items[-1]['label']=='Fold a strip into three equal panels.'
            assert stored(app)['state']['tabs'][0]['items']==items
            page.locator('[data-object="PAGE-B"]').click()
            page.locator('[data-paragraph="PAR-C"]').wait_for()
            assert page.locator('#sidebar').is_hidden()
            page.locator('#toggle-sidebar').click()
            page.locator(f'[data-item="{items[-1]["id"]}"] button').click()
            page.wait_for_function("document.activeElement?.dataset.paragraph==='PAR-A'")
            assert page.locator('[data-paragraph="PAR-C"]').count()==0
            editor=page.locator('[data-paragraph="PAR-A"]');editor.fill('Synthetic revision <b>plain text</b>')
            with page.expect_response('**/api/host'):page.locator('[data-object="PAGE-B"]').click()
            # Synchronize the independent stored document, not a displayed status flag.
            page.wait_for_function("async()=>{const d=await (await fetch('/api/document')).json();return d.nodes.find(x=>x.id==='PAR-A').text==='Synthetic revision <b>plain text</b>'}")
            app.stop();app.start();page.set_default_timeout(5000);page.goto(app.url)
            assert app.request('/api/state')['tabs'][0]['items']==items
            page.locator(f'[data-item="{items[-1]["id"]}"] button').click()
            page.wait_for_function("document.activeElement?.dataset.paragraph==='PAR-A'")
            assert page.locator('[data-paragraph="PAR-A"]').inner_text()=='Synthetic revision <b>plain text</b>'
            assert page.locator('#editor b').count()==0
            for item in items[:-1]:
                page.locator(f'[data-item="{item["id"]}"] button').click()
                page.wait_for_function('(id)=>fetch("/api/document").then(r=>r.json()).then(d=>d.current===id)',arg=item['target_id'])
                assert page.locator('#document-title').inner_text()
        finally:browser.close()


def folders():
    with App(PROJECT) as app, sync_playwright() as p:
        action(app,'folder',id='ROOT',label=' Root ')
        action(app,'folder',id='CHILD',label='Child',parent_id='ROOT')
        action(app,'bookmark',id='MARK',target_id='PAGE-B',parent_id='CHILD')
        action(app,'view',expanded=['ROOT','CHILD'])
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page();page.set_default_timeout(5000);page.goto(app.url);page.locator('[data-item="MARK"]').wait_for()
            page.locator('[data-item="CHILD"] .label').dblclick()
            page.get_by_label('Rename item').fill('Renamed child')
            with page.expect_response('**/api/action'):page.get_by_label('Rename item').press('Enter')
            page.wait_for_function("document.querySelector('[data-item=CHILD] .label')?.textContent==='Renamed child'")
            page.locator('[data-item="MARK"]').click()
            page.once('dialog',lambda d:d.dismiss());page.locator('#delete-item').click()
            assert page.locator('[data-item="MARK"]').count()==1
            page.once('dialog',lambda d:d.accept())
            with page.expect_response('**/api/action'):page.locator('#delete-item').click()
            page.wait_for_function("!document.querySelector('[data-item=MARK]')")
        finally:browser.close()
        before=app.request('/api/state')
        assert app.request('/api/action',{'type':'delete','id':'ROOT'},status=400)=={'error':'confirmation_required'}
        assert app.request('/api/action',{'type':'delete','id':'ROOT','confirmed':True},status=400)=={'error':'folder_not_empty'}
        assert app.request('/api/state')==before
        result=action(app,'delete',id='ROOT',confirmed=True,recursive=True)
        assert result['tabs'][0]['items']==[] and result['expanded']==[]
        assert len(app.request('/api/document')['nodes'])==12


def run():
    host_and_bookmarks();folders();print('Public notebook host and nested folder checks passed')


if __name__=='__main__':preflight();run()
