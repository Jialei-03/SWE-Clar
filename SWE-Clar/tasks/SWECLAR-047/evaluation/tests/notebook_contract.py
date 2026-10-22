import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,'/public_tests')
from harness import App
from preflight import preflight
from test_public import host_and_bookmarks,folders,action,stored
from playwright.sync_api import sync_playwright,Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def ids(items):return [x['id'] for x in items]
def find(state,key):
    def walk(items):
        for x in items:
            if x['id']==key:return x
            found=walk(x.get('children',[]))
            if found:return found
    for tab in state['tabs']:
        found=walk(tab['items'])
        if found:return found
def tab(state,key):return next(t for t in state['tabs'] if t['id']==key)


def moves():
    with App(PROJECT) as app:
        action(app,'folder',id='F',label='Folder')
        action(app,'folder',id='N',label='Nested',parent_id='F')
        action(app,'bookmark',id='B',target_id='PAR-C',parent_id='N')
        action(app,'bookmark',id='A',target_id='PAGE-A')
        action(app,'bookmark',id='C',target_id='PAGE-C')
        action(app,'tab',id='OTHER',name='Other')
        before=action(app,'view',expanded=['F','N']);assert before['active_tab']=='HOME'
        state=action(app,'move',ids=['C','F'],tab_id='OTHER')
        assert ids(tab(state,'HOME')['items'])==['A']
        assert ids(tab(state,'OTHER')['items'])==['C','F']
        assert find(state,'F')==find(before,'F') and state['expanded']==['F','N'] and state['active_tab']=='HOME'
        state=action(app,'move',ids=['A'],tab_id='OTHER',parent_id='N',index=0)
        assert ids(find(state,'N')['children'])==['A','B'] and tab(state,'HOME')['items']==[]
        state=action(app,'move',ids=['A'],tab_id='OTHER',parent_id='N',index=1)
        assert ids(find(state,'N')['children'])==['B','A']
        state=action(app,'move',ids=['B','A'],tab_id='HOME',index=0)
        assert ids(tab(state,'HOME')['items'])==['B','A'] and find(state,'N')['children']==[]
        state=action(app,'activate',id='OTHER');snapshot=stored(app)
        app.stop();app.start();assert stored(app)==snapshot and app.request('/api/state')==state
        # Many nested levels must work as an actual tree rather than a two-level special case.
        parent=None
        for i in range(18):
            key=f'DEPTH-{i}';action(app,'folder',id=key,label=key,tab_id='HOME',parent_id=parent);parent=key
        action(app,'bookmark',id='DEEP',target_id='PAR-D',tab_id='HOME',parent_id=parent)
        state=action(app,'move',ids=['DEPTH-0'],tab_id='OTHER',parent_id='N')
        assert find(state,'DEEP')['target_id']=='PAR-D'
        before=stored(app)
        faults=[({'ids':[],'tab_id':'HOME'},'invalid_command'),
                ({'ids':['F','F'],'tab_id':'HOME'},'duplicate_selection'),
                ({'ids':['F','N'],'tab_id':'HOME'},'overlapping_selection'),
                ({'ids':['F'],'tab_id':'OTHER','parent_id':'N'},'cyclic_move'),
                ({'ids':['F'],'tab_id':'OTHER','parent_id':'F'},'cyclic_move'),
                ({'ids':['C','MISSING'],'tab_id':'HOME'},'missing_item'),
                ({'ids':['C'],'tab_id':'HOME','parent_id':'N'},'invalid_parent'),
                ({'ids':['F'],'tab_id':'OTHER','parent_id':'C'},'invalid_parent'),
                ({'ids':['C'],'tab_id':'MISSING'},'missing_tab'),
                ({'ids':['B'],'tab_id':'HOME','index':99},'invalid_index'),
                ({'ids':['B'],'tab_id':'HOME','index':True},'invalid_index'),
                ({'ids':['B'],'tab_id':'HOME','index':-1},'invalid_index')]
        for command,code in faults:
            assert app.request('/api/action',dict(type='move',**command),status=400)=={'error':code}
            assert stored(app)==before


def interaction():
    with App(PROJECT) as app,sync_playwright() as p:
        action(app,'folder',id='F',label='Folder')
        for key,target in [('M1','PAR-A'),('M2','PAGE-B'),('M3','PAGE-C')]:action(app,'bookmark',id=key,target_id=target)
        action(app,'tab',id='NEXT',name='Next');action(app,'view',expanded=['F'])
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page(viewport={'width':1200,'height':850});page.set_default_timeout(5000);page.goto(app.url)
            page.locator('[data-item="M3"] .label').click()
            page.locator('[data-item="M1"] .label').click(modifiers=['Control'])
            with page.expect_response('**/api/action'):page.locator('[data-item="M3"]').drag_to(page.locator('[data-item="F"]'))
            state=app.request('/api/state');assert ids(find(state,'F')['children'])==['M3','M1']
            assert ids(tab(state,'HOME')['items'])==['F','M2']
            page.locator('[data-item="M3"] .label').click()
            page.locator('[data-item="M2"] .label').click(modifiers=['Shift'])
            with page.expect_response('**/api/action'):page.locator('[data-item="M3"]').drag_to(page.locator('[data-tab="NEXT"]'))
            state=app.request('/api/state');assert ids(tab(state,'NEXT')['items'])==['M3','M1','M2'] and state['active_tab']=='HOME'
            with page.expect_response('**/api/action'):page.locator('[data-tab="NEXT"]').click()
            page.locator('[data-item="M3"] .label').click();page.locator('[data-item="M3"]').press('ArrowDown')
            assert page.evaluate('document.activeElement.dataset.item')=='M1'
            # M1 points elsewhere: an accidental open on rename must be observable.
            app.request('/api/host',{'type':'navigate','id':'PAGE-B'})
            page.reload();page.locator('[data-item="M1"]').focus()
            document_before=app.request('/api/document')
            page.locator('[data-item="M1"]').press('F2');page.get_by_label('Rename item').fill('<img src=x> A new label')
            with page.expect_response('**/api/action'):page.get_by_label('Rename item').press('Enter')
            page.wait_for_function("document.querySelector('[data-item=M1] .label')?.textContent==='<img src=x> A new label'")
            assert page.locator('#tree img').count()==0
            assert app.request('/api/document')==document_before
            page.locator('[data-item="M1"]').press('F2');page.get_by_label('Rename item').fill('Cancelled');page.get_by_label('Rename item').press('Escape')
            assert find(app.request('/api/state'),'M1')['label']=='<img src=x> A new label'
            assert app.request('/api/document')==document_before
            page.locator('[data-item="M1"]').press('Enter');page.wait_for_function("document.activeElement.dataset.paragraph==='PAR-A'")
            page.locator('[data-item="M2"] .label').click()
            with page.expect_response('**/api/action'):page.locator('[data-item="M2"]').drag_to(page.locator('[data-item="M3"]'))
            assert ids(tab(app.request('/api/state'),'NEXT')['items'])==['M2','M3','M1']
            with page.expect_response('**/api/action'):page.locator('[data-tab="HOME"]').click()
            action(app,'bookmark',id='CHILD',target_id='PAR-D',parent_id='F')
            page.reload();page.locator('[data-item="CHILD"]').wait_for()
            page.locator('[data-item="F"] .label').click()
            with page.expect_response('**/api/action'):page.locator('[data-item="F"]').press('ArrowLeft')
            assert not page.locator('[data-item="CHILD"]').is_visible()
            with page.expect_response('**/api/action'):page.locator('[data-item="F"]').press('ArrowRight')
            assert page.locator('[data-item="CHILD"]').is_visible()
        finally:browser.close()
    with App(PROJECT) as app:
        for key,name in [('Z','zeta'),('A','Alpha'),('AA','alpha'),('BE','Beta')]:action(app,'folder',id=key,label=name)
        action(app,'bookmark',id='B1',target_id='PAGE-A');action(app,'folder',id='N',label='Nested',parent_id='Z')
        action(app,'bookmark',id='B2',target_id='PAGE-B')
        before=app.request('/api/state');state=action(app,'sort')
        assert ids(tab(state,'HOME')['items'])==['A','AA','BE','Z','B1','B2']
        assert find(state,'Z')==find(before,'Z')


def durability():
    with App(PROJECT) as app,sync_playwright() as p:
        action(app,'folder',id='F',label='Folder');action(app,'tab',id='NEXT',name='Next')
        action(app,'bookmark',id='LONG',target_id='PAR-A',label='Long synthetic bookmark label with several words that must visibly wrap',tab_id='NEXT')
        action(app,'view',expanded=['F'],width=180);action(app,'activate',id='NEXT')
        browser=_isolated_browser_launch(p.chromium, headless=True)
        try:
            page=browser.new_page(viewport={'width':1200,'height':850});page.set_default_timeout(5000);page.goto(app.url)
            row=page.locator('[data-item="LONG"] .label');row.wait_for();short=row.bounding_box()['height']
            page.locator('#sidebar').click(button='right');page.locator('#word-wrap').check()
            page.wait_for_function('(height)=>document.querySelector(\'[data-item="LONG"] .label\').getBoundingClientRect().height>height*1.5',arg=short)
            assert row.bounding_box()['height']>short*1.5
            handle=page.locator('#resize').bounding_box();page.mouse.move(handle['x']+3,100);page.mouse.down();page.mouse.move(360,100,steps=8)
            with page.expect_response('**/api/action'):page.mouse.up()
            page.wait_for_function("Math.round(document.querySelector('#sidebar').getBoundingClientRect().width)===360")
            state=app.request('/api/state');assert state['width']==360 and state['wrap'] is True and state['active_tab']=='NEXT' and state['expanded']==['F']
            snapshot=stored(app);app.stop();app.start();page.set_default_timeout(5000);page.goto(app.url);row=page.locator('[data-item="LONG"] .label');row.wait_for()
            assert app.request('/api/state')==state and stored(app)==snapshot
            assert page.locator('#sidebar').bounding_box()['width']==360 and row.bounding_box()['height']>short*1.5
            assert page.locator('[data-item="LONG"]').is_visible()
            assert page.locator('[data-item="F"]').count()==0
        finally:browser.close()
        before=stored(app)
        faults=[{'type':'bookmark','id':'LONG','target_id':'PAR-A'}, {'type':'tab','id':'F','name':'duplicate'},
                {'type':'bookmark','id':'NEW','target_id':'https://invalid.test'}, {'type':'folder','id':'NEW','label':' '},
                {'type':'view','width':179},{'type':'view','width':481},{'type':'view','width':True},{'type':'view','wrap':1},
                {'type':'view','width':333,'expanded':['F','F']},{'type':'view','expanded':['LONG']},{'type':'view','expanded':['MISSING']},
                {'type':'rename','id':'LONG','label':'x'*121},{'type':'activate','id':'MISSING'},{'type':'open','id':'F'}, {'type':'nonsense'}]
        for command in faults:
            response=app.request('/api/action',command,status=400);assert isinstance(response.get('error'),str)
            assert stored(app)==before,command
        app.request('/api/host',{'type':'edit','id':'PAGE-A','text':'forbidden'},status=400)
        app.request('/api/host',{'type':'navigate','id':'MISSING'},status=400);assert stored(app)==before
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda i:action(app,'bookmark',id=f'CONCURRENT-{i}',target_id='PAGE-A',tab_id='HOME'),range(24)))
        state=app.request('/api/state');assert set(ids(tab(state,'HOME')['items']))=={'F'}|{f'CONCURRENT-{i}' for i in range(24)}
        assert stored(app)['document']==before['document']


def main():
    try:prepared=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([host_and_bookmarks,folders,moves,interaction,durability],1):
        try:test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:
            results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':prepared,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
