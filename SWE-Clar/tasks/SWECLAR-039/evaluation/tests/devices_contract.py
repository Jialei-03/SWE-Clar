import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import contextlib
import copy
import io
import json
import os
import struct
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,'/public_tests')
from harness import App
from preflight import preflight
from peer_support import Peer,frame
from test_public import run as public_run
from playwright.sync_api import sync_playwright,Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


class TestPeer(Peer):
    def __init__(self):
        super().__init__();self.mode='good';self.connected=None;self.paired=set()
        self.codes={'DEV-A':'PAIR-'+uuid.uuid4().hex,'DEV-B':'PAIR-'+uuid.uuid4().hex}
        self.devices=[{'device_id':'DEV-A','name':'Device A','services':['capture.v1']},
                      {'device_id':'DEV-B','name':'Device B','services':['capture.v1']}]
        self.next_packets=[];self.marker='response-'+uuid.uuid4().hex
    def respond(self,r):
        if r['op']=='scan':return [{'ok':True,'devices':self.devices}]
        if r['op']=='pair':
            valid=r.get('device_id') in self.codes and self.codes[r['device_id']]==r.get('code')
            if valid:self.codes.pop(r['device_id']);self.paired.add(r['device_id'])
            return [{'ok':valid}]
        if r['op']=='connect':
            valid=r.get('device_id') in self.paired
            if valid:self.connected=r['device_id']
            return [{'ok':valid}]
        if r['op']=='disconnect':self.connected=None;return [{'ok':True}]
        if r['op']!='command' or r.get('device_id')!=self.connected:return [{'ok':False}]
        response={'ok':True,'command_id':r['command_id'],'result':{'marker':self.marker,'name':r['name'],'nested':[1,'信号',{'v':2.5}]},'packet_count':len(self.next_packets)}
        packets=copy.deepcopy(self.next_packets);mode=self.mode
        if mode=='wrong-id':response['command_id']='WRONG'
        elif mode=='bad-count':response['packet_count']=65
        elif mode=='bool-count':response['packet_count']=True
        elif mode=='bad-result':response['result']=[]
        elif mode=='bad-packet':packets=[{'device_id':self.connected,'packet_id':'X','data':[]}];response['packet_count']=1
        elif mode=='nan-data':packets=[{'device_id':self.connected,'packet_id':'X','data':{'v':float('nan')}}];response['packet_count']=1
        elif mode=='overflow-data':
            payload=b'{"device_id":"DEV-A","packet_id":"X","data":{"v":1e999}}'
            return frame(dict(response,packet_count=1))+struct.pack('!I',len(payload))+payload
        elif mode=='missing-packet':return [dict(response,packet_count=1)]
        elif mode=='zero-length':return b'\0\0\0\0'
        elif mode=='large-length':return struct.pack('!I',65537)
        elif mode=='short-header':return b'\0\0'
        elif mode=='truncated':return struct.pack('!I',100)+b'{}'
        elif mode=='invalid-json':return struct.pack('!I',3)+b'{x}'
        elif mode=='invalid-utf8':return struct.pack('!I',1)+b'\xff'
        elif mode=='nonobject':return [[]]
        elif mode=='invalid-ok':response['ok']=1
        elif mode=='denied':return [{'ok':False}]
        elif mode=='timeout':time.sleep(2.3)
        return [response,*packets]


def scan(app):return app.request('/api/scan',{'service':'capture.v1'})
def connect(app,peer,device='DEV-A'):
    scan(app)
    if device in peer.codes:app.request('/api/pair',{'device_id':device,'code':peer.codes[device]})
    return app.request('/api/connect',{'device_id':device})
def send(app,device='DEV-A',key='CMD-1',name='status',status=200):
    return app.request('/api/command',{'device_id':device,'command_id':key,'name':name},status=status)


def ru1():
    with contextlib.redirect_stdout(io.StringIO()):public_run()


def ru2():
    with TestPeer() as peer,App(PROJECT,['--peer-port',str(peer.port)]) as app:
        peer.devices=[{'device_id':'Z','name':'old','services':['capture.v1']},
                      {'device_id':'A','name':'A','services':['capture.v1']},
                      {'device_id':'Z','name':'updated','services':['other','capture.v1']},
                      {'device_id':'B','name':'drop','services':['capture.v1']},
                      {'device_id':'B','name':'changed','services':['other']}]
        result=scan(app)
        assert result['devices']==[peer.devices[2],peer.devices[1]]
        peer.fragment=False;peer.devices=[{'device_id':'FRESH','name':'Only new','services':['capture.v1']}]
        current=scan(app);assert current['devices']==peer.devices
        for invalid in [[{'device_id':'','name':'x','services':[]}],[{'device_id':'X','name':1,'services':[]}],
                        [{'device_id':'X','name':'x','services':['capture.v1',1]}],{},[{'device_id':'X','name':'x'}]]:
            peer.devices=invalid;app.request('/api/scan',{'service':'capture.v1'},status=502)
            assert app.request('/api/state')['devices']==current['devices']
        peer.devices=[];assert scan(app)['devices']==[]


def ru3():
    with TestPeer() as peer,App(PROJECT,['--peer-port',str(peer.port)]) as app:
        app.request('/api/pair',{'device_id':'DEV-A','code':''},status=400)
        code=peer.codes['DEV-A']
        app.request('/api/pair',{'device_id':'DEV-A','code':code},status=409);assert peer.requests==[]
        scan(app);app.request('/api/connect',{'device_id':'DEV-A'},status=409)
        app.request('/api/pair',{'device_id':'DEV-A','code':'wrong'},status=403)
        assert app.request('/api/state')['paired']==[]
        paired=app.request('/api/pair',{'device_id':'DEV-A','code':code})
        assert paired['paired']==['DEV-A'] and 'DEV-A' not in peer.codes
        count=len(peer.requests);assert app.request('/api/pair',{'device_id':'DEV-A','code':'unused'})==paired;assert len(peer.requests)==count
        assert code.encode() not in app.db.read_bytes() and code not in json.dumps(paired)
        before=app.request('/api/connect',{'device_id':'DEV-A'});assert before['connected']=='DEV-A' and peer.connected=='DEV-A'
        count=len(peer.requests);assert app.request('/api/connect',{'device_id':'DEV-A'})==before;assert len(peer.requests)==count
        app.request('/api/pair',{'device_id':'DEV-B','code':peer.codes['DEV-B']})
        app.request('/api/connect',{'device_id':'DEV-B'},status=409)
        disconnected=app.request('/api/disconnect',{});assert disconnected['connected'] is None and set(disconnected['paired'])=={'DEV-A','DEV-B'} and peer.connected is None
        count=len(peer.requests);assert app.request('/api/disconnect',{})==disconnected;assert len(peer.requests)==count
        app.request('/api/connect',{'device_id':'DEV-A'});assert scan(app)['connected']=='DEV-A'
        app.stop();app.start()
        restarted=app.request('/api/state')
        assert restarted['connected'] is None and restarted['devices']==[] and set(restarted['paired'])=={'DEV-A','DEV-B'}
        scan(app);app.request('/api/connect',{'device_id':'DEV-A'})
        peer.devices=[peer.devices[1]];assert scan(app)['connected'] is None
        app.stop();app.start();state=app.request('/api/state');assert state['devices']==[] and state['connected'] is None and set(state['paired'])=={'DEV-A','DEV-B'}
        for path,body in [('/api/pair',{'device_id':True,'code':'x'}),('/api/pair',{'device_id':'DEV-B','code':''}),('/api/connect',{'device_id':'bad id'})]:
            if body.get('device_id')=='DEV-B':scan(app)
            app.request(path,body,status=400)
    # The default synthetic child peer also retains consumed-code/paired state across restart.
    with App(PROJECT) as app:
        scan(app);app.request('/api/pair',{'device_id':'SENSOR-A','code':'DEMO-PAIR-A'})
        app.stop();app.start();scan(app)
        assert app.request('/api/connect',{'device_id':'SENSOR-A'})['connected']=='SENSOR-A'


def ru4():
    with TestPeer() as peer,App(PROJECT,['--peer-port',str(peer.port)]) as app:
        send(app,status=409);assert peer.requests==[];connect(app,peer)
        count=len(peer.requests)
        for name in ['unknown','STATUS',None]:send(app,key='BAD',name=name,status=400)
        send(app,device='DEV-B',status=409);assert len(peer.requests)==count
        peer.next_packets=[{'device_id':'DEV-A','packet_id':'P1','data':{'value':3,'nested':['<tag>',{'u':'温度'}]}},
                           {'device_id':'DEV-B','packet_id':'FOREIGN','data':{'value':8}},
                           {'device_id':'DEV-A','packet_id':'P1','data':{'value':99}},
                           {'device_id':'DEV-A','packet_id':'P2','data':{'value':4}}]
        result=send(app);assert result=={'result':{'marker':peer.marker,'name':'status','nested':[1,'信号',{'v':2.5}]}}
        state=app.request('/api/state');assert state['telemetry']==[peer.next_packets[0],peer.next_packets[3]] and len(state['commands'])==1
        count=len(peer.requests);assert send(app)==result;assert len(peer.requests)==count;assert app.request('/api/state')==state
        send(app,name='start',status=409);assert len(peer.requests)==count
        peer.next_packets=[{'device_id':'DEV-A','packet_id':'P2','data':{'value':100}}, {'device_id':'DEV-A','packet_id':'P3','data':{'v':[1,2]}}]
        send(app,key='CMD-2',name='start');assert app.request('/api/state')['telemetry']==state['telemetry']+[peer.next_packets[1]]
        peer.next_packets=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            batch=list(pool.map(lambda _:send(app,key='RETRY',name='calibrate'),range(10)))
        assert all(r==batch[0] for r in batch)
        assert len([r for r in peer.requests if r.get('command_id')=='RETRY'])==1
        saved=app.request('/api/state');app.request('/api/disconnect',{});assert app.request('/api/state')['telemetry']==saved['telemetry']
        app.stop();app.start();connect(app,peer)
        count=len(peer.requests);assert send(app)==result;assert len(peer.requests)==count
        for mode in ['wrong-id','bad-count','bool-count','bad-result','bad-packet','nan-data','overflow-data','missing-packet',
                     'zero-length','large-length','short-header','truncated','invalid-json','invalid-utf8','nonobject','invalid-ok','timeout']:
            peer.mode=mode;before=app.request('/api/state');send(app,key='FAULT-'+mode,status=502)
            after=app.request('/api/state');assert after==dict(before,connected=None),mode
            peer.mode='good';app.request('/api/connect',{'device_id':'DEV-A'});send(app,key='FAULT-'+mode)
        peer.mode='denied';before=app.request('/api/state');send(app,key='DENIED',status=403);assert app.request('/api/state')==before
        peer.mode='good';app.request('/api/disconnect',{});connect(app,peer,'DEV-B');send(app,device='DEV-B',key='CMD-1',status=409)


def columns(a,b):
    return b['x']>=a['x']+a['width'] and min(a['y']+a['height'],b['y']+b['height'])>max(a['y'],b['y'])

def ru5():
    with TestPeer() as peer,App(PROJECT,['--peer-port',str(peer.port)]) as app:
        code=peer.codes['DEV-A'];peer.next_packets=[{'device_id':'DEV-A','packet_id':'UI-P','data':{'reading':'<img src=x onerror=alert(1)>','nested':{'value':12}}}]
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True)
            try:
                page=browser.new_page(viewport={'width':1024,'height':900});page.goto(app.url)
                page.locator('#scan').click();page.locator('[data-device="DEV-A"]').click();page.locator('#pair-code').fill(code)
                with page.expect_response('**/api/pair'):page.locator('#pair').click()
                with page.expect_response('**/api/connect'):page.locator('#connect').click()
                page.wait_for_function("document.querySelector('#connection').textContent === 'DEV-A'")
                page.locator('#command-id').fill('UI-CMD');page.locator('#send').click();page.locator('[data-packet="UI-P"]').wait_for()
                assert page.locator('#telemetry img').count()==0
                assert '<img src=x' in page.locator('#telemetry').inner_text()
                before=app.request('/api/state');requests=len(peer.requests)
                for width in [320,767,768,1024,360,900]:
                    page.set_viewport_size({'width':width,'height':1000})
                    page.wait_for_function('(width)=>window.innerWidth===width',arg=width)
                    a=page.locator('#device-panel').bounding_box();b=page.locator('#telemetry-panel').bounding_box()
                    if width<768:assert b['y']>=a['y']+a['height'] and abs(a['x']-b['x'])<1, ('stack',width,a,b)
                    else:assert columns(a,b), ('columns',width,a,b)
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), ('horizontal overflow',width,page.evaluate('document.documentElement.scrollWidth'))
                    assert page.locator('#device').input_value()=='DEV-A' and page.locator('#connection').inner_text()=='DEV-A'
                    assert page.locator('[data-packet="UI-P"]').count()==1
                assert app.request('/api/state')==before and len(peer.requests)==requests
            finally:browser.close()


def main():
    try:health=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([ru1,ru2,ru3,ru4,ru5],1):
        try:test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:
            results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':health,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
