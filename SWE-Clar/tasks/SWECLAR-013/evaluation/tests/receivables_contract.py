import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import csv
import io
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, '/opt/sweclar')
from harness import App, CandidateFailure
from preflight import preflight
from playwright.sync_api import sync_playwright, Error as BrowserError

PROJECT = Path(os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))
HEADER = 'account_id,balance_cents,age_days\n'


def import_rows(app, rows):
    return app.request('/api/import', HEADER + '\n'.join(','.join(map(str,row)) for row in rows) + '\n')


def follow(app, ids, status='contacted', note='Follow-up recorded', expected=200):
    return app.request('/api/follow-ups', {'account_ids':ids,'status':status,'note':note},status=expected)


def ru1():
    with App(PROJECT) as app, sync_playwright() as p:
        browser = _isolated_browser_launch(p.chromium, headless=True)
        try:
            page = browser.new_page(viewport={'width':800,'height':900})
            page.goto(app.url)
            page.locator('#file').set_input_files({'name':'synthetic.csv','mimeType':'text/csv','buffer':(HEADER+'WEB-C,42000,92\nWEB-A,8700,18\n').encode()})
            page.get_by_role('button',name='Import CSV',exact=True).click()
            page.get_by_role('button',name='WEB-C',exact=True).wait_for()
            assert [r['account_id'] for r in app.request('/api/accounts')['accounts']]==['WEB-A','WEB-C']
            page.get_by_role('checkbox',name='Select WEB-C',exact=True).check()
            page.locator('#status').select_option('contacted')
            page.locator('#note').fill('Called the synthetic account')
            with page.expect_response('**/api/follow-ups') as response:
                page.get_by_role('button',name='Save follow-up',exact=True).click()
            assert response.value.status==200
            page.get_by_role('button',name='WEB-C',exact=True).click()
            page.locator('#detail h3').wait_for()
            assert app.request('/api/accounts/WEB-C')['account']['note']=='Called the synthetic account'
            with page.expect_download() as event:
                page.get_by_role('link',name='Export queue',exact=True).click()
            assert event.value.failure() is None
            data=list(csv.DictReader(io.StringIO(Path(event.value.path()).read_text())))
            assert any(r['account_id']=='WEB-C' for r in data)
            before=app.request('/api/accounts')['accounts']
            app.stop(); app.start()
            assert app.request('/api/accounts')['accounts']==before
            app.request('/api/accounts/MISSING',status=404)
        finally:
            browser.close()


def ru2():
    with App(PROJECT) as app:
        import_rows(app,[('IMP-A',100,90),('KEEP-B',200,12)])
        follow(app,['IMP-A'])
        before=app.request('/api/accounts/IMP-A')
        import_rows(app,[('IMP-A',321,88),('NEW-C',500,33)])
        after=app.request('/api/accounts/IMP-A')
        assert after['account']['balance_cents']==321 and after['account']['age_days']==88
        assert after['account']['status']==before['account']['status'] and after['account']['note']==before['account']['note']
        assert after['history']==before['history']
        assert len(app.request('/api/accounts')['accounts'])==3
        import_rows(app,[('IMP-A',321,88),('NEW-C',500,33)])
        assert app.request('/api/accounts/IMP-A')==after
        snapshot=app.request('/api/accounts')
        invalid=[HEADER,HEADER+'IMP-A,7,2\nIMP-A,8,3\n',HEADER+'IMP-A,999,5\nBROKEN,2.5,8\n',
                 HEADER+'BAD ID,2,4\n',HEADER+'IMP-A,4,-1\n',HEADER+'IMP-A,1000000000001,4\n',
                 HEADER+'IMP-A,4,36501\n',HEADER+'IMP-A,4,5,extra\n','wrong,header\na,b\n']
        for text in invalid:
            app.request('/api/import',text,status=400)
            assert app.request('/api/accounts')==snapshot


def ru3():
    with App(PROJECT) as app:
        import_rows(app,[('EDGE-60',1,60),('EDGE-61',1,61),('ZERO',0,100),('CREDIT',-1,120),
                         ('TIE-B',20,90),('TIE-A',30,90),('CLOSED',15,140)])
        follow(app,['CLOSED'],'resolved','Settled')
        assert [r['account_id'] for r in app.request('/api/queue')['accounts']]==['TIE-A','TIE-B','EDGE-61']
        import_rows(app,[('EDGE-60',20,91)])
        assert [r['account_id'] for r in app.request('/api/queue')['accounts']]==['EDGE-60','TIE-A','TIE-B','EDGE-61']
        follow(app,['CLOSED'],'open','')
        assert app.request('/api/queue')['accounts'][0]['account_id']=='CLOSED'


def ru4():
    with App(PROJECT) as app:
        import_rows(app,[('BATCH-A',120,90),('BATCH-B',300,100)])
        snapshot={k:app.request('/api/accounts/'+k) for k in ['BATCH-A','BATCH-B']}
        invalid=[([], 'open',''),(['BATCH-A','BATCH-A'],'contacted','n'),(['BATCH-A','MISSING'],'contacted','n'),
                 (['BATCH-A'],'unknown','n'),(['BATCH-A'],'resolved',' \n '),(['BATCH-B'],'open','x'*2001)]
        for ids,status,note in invalid:
            follow(app,ids,status,note,400)
            assert {k:app.request('/api/accounts/'+k) for k in snapshot}==snapshot
        assert follow(app,['BATCH-A','BATCH-B'],'disputed','  Needs review  ')['updated']==2
        for key in snapshot:
            detail=app.request('/api/accounts/'+key)
            assert detail['account']['note']=='Needs review' and detail['account']['status']=='disputed'
            assert len(detail['history'])==1
            event=detail['history'][0]
            assert {k:event[k] for k in ['account_id','before_status','after_status','before_note','after_note']}=={
                'account_id':key,'before_status':'open','after_status':'disputed','before_note':'','after_note':'Needs review'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            assert all(r['updated']==0 for r in pool.map(lambda _:follow(app,['BATCH-A','BATCH-B'],'disputed','Needs review'),range(10)))
        preserved={k:app.request('/api/accounts/'+k) for k in snapshot}
        for payload in [{'account_ids':['BATCH-A'],'status':'open'},
                        *[{'account_ids':['BATCH-A'],'status':'open','note':value}
                          for value in [None,7,False,[],{}]]]:
            app.request('/api/follow-ups',payload,status=400)
            assert {k:app.request('/api/accounts/'+k) for k in snapshot}==preserved
        assert follow(app,['BATCH-B'],'contacted','  Replacement note  ')['updated']==1
        replaced=app.request('/api/accounts/BATCH-B')
        assert replaced['account']['note']=='Replacement note'
        assert replaced['history'][-1]['before_note']=='Needs review'
        assert replaced['history'][-1]['after_note']=='Replacement note'
        assert follow(app,['BATCH-A'],'open','')['updated']==1
        before=app.request('/api/accounts/BATCH-A')
        assert before['account']['note']==''
        assert len(before['history'])==2 and before['history'][1]['sequence']>before['history'][0]['sequence']
        app.stop(); app.start()
        assert app.request('/api/accounts/BATCH-A')==before
        assert len(app.request('/api/accounts/BATCH-B')['history'])==2


def ru5():
    with App(PROJECT) as app:
        assert app.request('/api/export',raw=True).strip()=='account_id,balance_cents,age_days,status,note'
        import_rows(app,[('CSV-A',100,100),('CSV-B',200,120),('YOUNG',50,12),('RESOLVED',100,130)])
        follow(app,['RESOLVED'],'resolved','Settled')
        notes=['comma, quote " and newline\n测试','=1+1','+SUM(1,2)','-2+3','@formula']
        for note in notes:
            follow(app,['CSV-A'],'contacted',note)
            exported=list(csv.DictReader(io.StringIO(app.request('/api/export',raw=True))))
            assert [r['account_id'] for r in exported]==['CSV-B','CSV-A']
            row=exported[1]
            expected="'"+note if note[0] in '=+-@' else note
            assert row=={'account_id':'CSV-A','balance_cents':'100','age_days':'100','status':'contacted','note':expected}
            assert app.request('/api/accounts/CSV-A')['account']['note']==note


def main():
    try:
        health=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}))
        return 2
    results=[]
    for index, test in enumerate([ru1,ru2,ru3,ru4,ru5],1):
        try:
            test()
            results.append({'ru_id':f'RU-{index:03d}','passed':True})
        except (AssertionError, BrowserError, KeyError, TypeError, ValueError) as error:
            results.append({'ru_id':f'RU-{index:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':health,'results':results},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
