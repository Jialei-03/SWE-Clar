import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import contextlib
import copy
import io
import json
import math
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
sys.path.insert(0,'/opt/sweclar')
sys.path.insert(0,'/public_tests')
from harness import App
from preflight import preflight
from worker_support import Worker
from test_public import run as public_run, drag
from playwright.sync_api import sync_playwright, Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def near(actual, expected): assert type(actual) in (int,float) and abs(actual-expected)<1e-6,(actual,expected)
def edit(app,index,x,y,shift=False,status=200):return app.request('/api/move',{'index':index,'x':x,'y':y,'shift':shift},status=status)


def ru1():
    with contextlib.redirect_stdout(io.StringIO()): public_run()
    # Also exercise the supplied runnable child driver, not only an external fixture.
    with App(PROJECT) as app:
        response=app.request('/api/send',{'positions':[0,20,60,100]})
        assert response['samples']==[{'x':0,'y':0},{'x':20,'y':15},{'x':60,'y':30},{'x':100,'y':30}]
        assert isinstance(response['receipt'],str)
        child_ids=Path(f'/proc/{app.process.pid}/task/{app.process.pid}/children').read_text().split()
        assert child_ids, 'The automatically started driver must be an owned child'
        children=[Path('/proc')/pid for pid in child_ids]
        app.stop()
        assert all(not child.exists() for child in children), 'Automatically started children must stop with their server'


def ru2():
    with Worker() as worker, App(PROJECT,['--driver-port',str(worker.port)]) as app:
        before=app.request('/api/curve')
        for index,x,y in [(1,80,2),(1,0,2),(1,-1,2),(1,40,-1),(1,40,101),(3,50,50),(-1,50,50),(True,50,50),(1,True,20),(1,float('nan'),0),(1,float('inf'),0)]:
            edit(app,index,x,y,status=400);assert app.request('/api/curve')==before
        for points in [[],[{'x':0,'y':0}], [{'x':5,'y':0},{'x':5,'y':1}], [{'x':6,'y':2},{'x':5,'y':2}], [{'x':1,'y':1},{}], [{'x':x,'y':1} for x in range(33)]]:
            app.request('/api/curve',{'points':points},status=400);assert app.request('/api/curve')==before
        changed=edit(app,2,90,80)
        assert changed['points'][:2]==before['points'][:2]
        near(changed['terminal_angle_degrees'],45)
        assert changed['revision']==1
        assert edit(app,2,90,80)==changed
        assert app.request('/api/curve',{'points':changed['points']})==changed
        for value in range(81,91):
            observed=edit(app,2,value,80)
            assert app.request('/api/curve')==observed
        revision=app.request('/api/curve')['revision']
        points=[{'x':0,'y':100},{'x':100,'y':0}]
        r=app.request('/api/curve',{'points':points});assert r['revision']==revision+1;near(r['terminal_angle_degrees'],-45)
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(app.url);page.locator('#point-1').wait_for()
                drag(page,1,0,20)
                page.wait_for_function("document.querySelector('#status').textContent.length > 0")
                assert app.request('/api/curve')==r
                near(float(page.locator('#point-1').get_attribute('cx')),580)
                near(float(page.locator('#point-1').get_attribute('cy')),380)
            finally:browser.close()


def ru3():
    with Worker() as worker, App(PROJECT,['--driver-port',str(worker.port)]) as app:
        base=app.request('/api/curve')
        r=edit(app,2,80,60,True)
        assert r['points'][:2]==base['points'][:2]
        near(r['points'][2]['x'],72);near(r['points'][2]['y'],54)
        near(r['terminal_angle_degrees'],math.degrees(math.atan2(3,4)))
        for index,x,y in [(1,20,20),(2,40,30),(2,0,30),(2,40,80)]:
            edit(app,index,x,y,True,400);assert app.request('/api/curve')==r
        app.request('/api/curve',{'points':[{'x':1,'y':1},{'x':70,'y':70},{'x':99,'y':99}]})
        before=app.request('/api/curve');edit(app,2,100,70,True,400);assert app.request('/api/curve')==before
        app.request('/api/curve',{'points':base['points']})
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page();page.goto(app.url);page.locator('#point-2').wait_for()
                with page.expect_response(lambda r:r.url.endswith('/api/move') and r.request.method=='POST') as acknowledged:
                    drag(page,2,80,0,True)
                assert acknowledged.value.status==200
                page.wait_for_function("Math.abs(Number(document.querySelector('#point-2').getAttribute('cx'))-423.2)<1e-6 && Math.abs(Number(document.querySelector('#point-2').getAttribute('cy'))-358.4)<1e-6")
                after=app.request('/api/curve');near(after['points'][2]['x'],72);near(after['points'][2]['y'],6)
                near(after['terminal_angle_degrees'],-math.degrees(math.atan2(3,4)))
                near(float(page.locator('#point-2').get_attribute('cx')),423.2)
                near(float(page.locator('#point-2').get_attribute('cy')),358.4)
                near(math.hypot(after['points'][2]['x']-40,after['points'][2]['y']-30),40)
            finally:browser.close()


class FaultWorker(Worker):
    def __init__(self):
        super().__init__();self.mode='good'
    def reply(self,request):
        mode=self.mode
        response=super().reply(request)
        if mode=='mismatch':response['sequence']+=1
        elif mode=='bool-sequence':response['sequence']=True
        elif mode=='missing-sample':response['samples'].pop()
        elif mode=='wrong-x':response['samples'][0]['x']+=1
        elif mode=='bool-x':response['samples'][0]['x']=True
        elif mode=='bool-y':response['samples'][0]['y']=True
        elif mode=='nan-y':response['samples'][0]['y']=float('nan')
        elif mode=='high-y':response['samples'][0]['y']=101
        elif mode=='huge-y':response['samples'][0]['y']=10**400
        elif mode=='negative-y':response['samples'][0]['y']=-1
        elif mode=='missing-receipt':response.pop('receipt')
        elif mode=='object-receipt':response['receipt']={}
        elif mode=='nonobject':return []
        elif mode=='invalid':return b'{invalid}\n'
        elif mode=='no-newline':return b'{}'
        elif mode=='oversize':return b' '+b'x'*65536+b'\n'
        elif mode=='disconnect':return None
        elif mode=='timeout':time.sleep(2.3)
        elif mode=='different-values':
            response['samples']=[{'x':x,'y':17+i} for i,x in enumerate(request['positions'])]
            response['extra']='ignore this field'
        return response


def ru4():
    with FaultWorker() as worker, App(PROJECT,['--driver-port',str(worker.port)]) as app:
        positions=[1,25,99,25]
        for body in [{'positions':[]},{'positions':[False]},{'positions':[101]},{'positions':[0]*65}]:
            before=app.request('/api/curve');app.request('/api/send',body,status=400);assert app.request('/api/curve')==before
        assert worker.requests==[]
        worker.mode='different-values';r=app.request('/api/send',{'positions':positions})
        assert r=={'sequence':1,'samples':[{'x':x,'y':17+i} for i,x in enumerate(positions)],'receipt':worker.receipt}
        assert worker.requests[-1]['positions']==positions
        worker.mode='good'
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            responses=list(pool.map(lambda _:app.request('/api/send',{'positions':[0,100]}),range(10)))
        assert sorted(r['sequence'] for r in responses)==list(range(2,12))
        assert [q['sequence'] for q in worker.requests]==list(range(1,12))
        faults=['mismatch','bool-sequence','missing-sample','wrong-x','bool-x','bool-y','nan-y','high-y','huge-y','negative-y','missing-receipt','object-receipt','nonobject','invalid','no-newline','oversize','disconnect','timeout']
        for mode in faults:
            before=app.request('/api/curve');worker.mode=mode
            response=app.request('/api/send',{'positions':positions},status=503)
            assert response=={'error':'driver_failure','sequence':before['next_sequence']},(mode,response)
            after=app.request('/api/curve')
            assert after==dict(before,next_sequence=before['next_sequence']+1),(mode,after)
            worker.mode='good'
            recovered=app.request('/api/send',{'positions':positions})
            assert recovered['sequence']==after['next_sequence'] and recovered['receipt']==worker.receipt
            assert app.request('/api/curve')['last_acknowledged']==after['next_sequence']
        before=app.request('/api/curve');app.stop();app.start();assert app.request('/api/curve')==before
        r=app.request('/api/send',{'positions':[10]});assert r['sequence']==before['next_sequence']
        assert [q['sequence'] for q in worker.requests]==list(range(1,r['sequence']+1))
        assert all(q['points']==before['points'] for q in worker.requests)


def ru5():
    # Fixture is independently generated, readable by the app but not served by it.
    with tempfile.TemporaryDirectory(prefix='sweclar-license-fixture-') as directory:
        os.chmod(directory,0o755);path=Path(directory)/'entitlements.json'
        first=str(uuid.uuid4());second=str(uuid.uuid4());key='SYNTHETIC-'+uuid.uuid4().hex
        records=[{'uuid':first,'product_key':key,'active':True},{'uuid':second,'product_key':'REVOKED-DEMO','active':False}]
        path.write_text(json.dumps(records));os.chmod(path,0o444)
        with Worker() as worker, App(PROJECT,['--driver-port',str(worker.port),'--licenses',str(path)]) as app:
            cases=[(first,key,True),(' '+first.upper()+' ',' '+key+' ',True),(first,key.lower(),False),
                   (first,'wrong',False),(second,'REVOKED-DEMO',False),(first.replace('-',''),key,False),
                   (str(uuid.uuid4()),key,False),('not-a-uuid',key,False),(first,'REVOKED-DEMO',False),(second,key,False)]
            for identifier,submitted,expected in cases:
                assert app.request('/api/license',{'uuid':identifier,'product_key':submitted})=={'valid':expected}
            for body in [{},{'uuid':first,'product_key':None},{'uuid':12,'product_key':key}]:
                app.request('/api/license',body,status=400)
            for route in ['/licenses.json','/entitlements.json','/api/licenses','/../'+str(path)]:app.request(route,status=404)
            assert key not in app.request('/',raw=True) and key not in json.dumps(app.request('/api/curve'))
            with sync_playwright() as p:
                browser=_isolated_browser_launch(p.chromium, headless=True)
                try:
                    page=browser.new_page();page.goto(app.url);page.locator('#license-uuid').fill(first.upper());page.locator('#license-key').fill(key)
                    page.locator('#check-license').click();page.wait_for_function("document.querySelector('#license-result').textContent === 'Valid'")
                    assert key not in page.locator('body').inner_text()
                    page.locator('#license-key').fill('wrong');page.locator('#check-license').click();page.wait_for_function("document.querySelector('#license-result').textContent === 'Invalid'")
                finally:browser.close()


def main():
    try:health=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([ru1,ru2,ru3,ru4,ru5],1):
        try:
            test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:
            results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':health,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
