import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import base64,copy,io,json,math,os,time,wave
from pathlib import Path
from conftest import call
from transport import App,wav

def fresh(participants=()):
    return {'admins':['admin'],'rooms':{'r':{'private':False,'access_token':'','turn_limit':10,'participants':list(participants),'locked':[],'current':None,'deadline':None}}}
def event(kind,**extra):return {'type':kind,'room_id':'r',**extra}
def ok(out):assert 'error' not in out,out.get('error');return out

def denied(state,action):
    out=call(state,action);code=out.get('error',{}).get('code');assert isinstance(code,str) and bool(code)
    assert out['rooms']==state['rooms'];return out

def test_ru_001_http_and_browser_playback():
    initial={'admins':['admin'],'rooms':{}}
    ok(call(initial,{'type':'create_room','admin_id':'admin','room_id':'baseline','private':False,'turn_limit':5}))
    state=fresh()
    for action in [None,[],{'type':'unknown','room_id':'r'}]:denied(state,action)
    with App() as app:
        assert app.get('/health')['ok'] is True
        for value in [b'{',None,[],{'type':'unknown'}]:
            out=app.post(value,400);assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
        assert app.get('/health')['ok'] is True
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=_isolated_browser_launch(p.chromium, headless=True, args=['--autoplay-policy=no-user-gesture-required'])
            try:
                speaker=browser.new_page();listener=browser.new_page()
                for page,user in [(speaker,'speaker'),(listener,'listener')]:
                    page.goto(app.url);page.get_by_label('Room',exact=True).fill('browser-room');page.get_by_label('Participant',exact=True).fill(user)
                def click(page,label):
                    with page.expect_response(lambda r:r.url.endswith('/events') and r.request.method=='POST') as response:page.get_by_role('button',name=label,exact=True).click()
                    assert response.value.status==200,response.value.text()
                click(speaker,'Create room');click(speaker,'Join');click(listener,'Join');click(speaker,'Advance');click(speaker,'Send sample audio')
                listener.get_by_role('button',name='Receive audio',exact=True).click();audio=listener.get_by_role('region',name='Received audio',exact=True).locator('audio');audio.wait_for();assert audio.count()==1
                observed=audio.evaluate('''async el=>{const bytes=await(await fetch(el.currentSrc||el.src)).arrayBuffer();const ctx=new AudioContext();const decoded=await ctx.decodeAudioData(bytes.slice(0));const samples=decoded.getChannelData(0);let energy=0;for(const x of samples)energy+=x*x;await ctx.close();const encoded=btoa(String.fromCharCode(...new Uint8Array(bytes)));await el.play();await new Promise(r=>setTimeout(r,100));return {encoded,duration:decoded.duration,channels:decoded.numberOfChannels,energy:energy/samples.length,controls:el.controls,progress:el.currentTime,playing:!el.paused||el.ended};}''')
                expected=app.get('/demo.wav',raw=True);assert base64.b64decode(observed['encoded'])==expected
                with wave.open(io.BytesIO(expected)) as f:assert (f.getnchannels(),f.getsampwidth(),f.getframerate())==(1,2,8000);assert f.getnframes()>0
                assert observed['controls'] and observed['progress']>0 and observed['playing'];assert observed['channels']==1 and observed['energy']>0 and observed['duration']>0
                assert app.inbox('speaker','browser-room')==[]
                with listener.expect_response(lambda r:'/inbox?' in r.url) as drained:listener.get_by_role('button',name='Receive audio',exact=True).click()
                assert drained.value.json()['packets']==[];assert audio.count()==1
            finally:browser.close()

def test_ru_002_creation_regression():
    state={'admins':['admin'],'rooms':{}}
    action={'type':'create_room','admin_id':'admin','room_id':'r','private':True,'access_token':'secret','turn_limit':10}
    out=ok(call(state,action));assert out['result']['room_id']=='r' and out['rooms']['r']['private'] is True
    denied(out,action)
    for extra in [{'admin_id':'outsider'},{'room_id':''},{'private':'yes'},{'turn_limit':0},{'turn_limit':True},{'turn_limit':float('inf')},{'turn_limit':float('nan')},{'access_token':''},{'access_token':123}]:denied(state,{**action,**extra})
    ok(call(state,{**action,'private':False,'access_token':''}))

def test_ru_003_join_lock_and_resume():
    state=fresh();state['rooms']['r'].update(private=True,access_token='required')
    denied(state,event('join',user_id='a',access_token='wrong'))
    for user in ['a','b','a','c']:
        state=ok(call(state,event('join',user_id=user,access_token='required')))
    assert state['result']['participants']==['a','b','c']
    for user in ['',None,[]]:denied(state,event('join',user_id=user,access_token='required'))
    denied(state,event('lock_pass',user_id='outside'))
    state=ok(call(state,event('advance',server_time=0)));assert state['result']['current']=='a'
    state=ok(call(state,event('lock_pass',user_id='a')));assert state['result']['locked'] is True;assert state['rooms']['r']['current'] is None and state['rooms']['r']['deadline'] is None
    state=ok(call(state,event('advance',server_time=2)));assert state['result']['current']=='b'
    state=ok(call(state,event('unlock_pass',user_id='a')));assert state['result']['locked'] is False;assert state['rooms']['r']['current']=='b'
    assert state['rooms']['r']['participants']==['a','b','c']

def test_ru_004_turn_deadlines_and_order():
    state=fresh(['a','b','c']);state['rooms']['r']['locked']=['b']
    state=ok(call(state,event('advance',server_time=5)));assert state['result']['current']=='a' and state['result']['deadline']==15
    denied(state,event('pass',user_id='c',server_time=6));denied(state,event('timeout',server_time=14.999))
    for when in [True,float('nan'),float('inf'),'15']:denied(state,event('advance',server_time=when))
    state=ok(call(state,event('timeout',server_time=15)));assert state['result']['current']=='c' and state['result']['deadline']==25
    state=ok(call(state,event('pass',user_id='c',server_time=16)));assert state['result']['current']=='a' and state['result']['deadline']==26
    for user in ['a','c']:state=ok(call(state,event('lock_pass',user_id=user)))
    state=ok(call(state,event('advance',server_time=17)));assert state['result']['current'] is None and state['result']['deadline'] is None
    denied(state,event('timeout',server_time=100))
    empty=ok(call(fresh(),event('advance',server_time=1)));assert empty['result']['current'] is None and empty['result']['deadline'] is None

def test_ru_005_wav_permissions_replay_and_real_inboxes():
    state=fresh(['a','b','c']);state['rooms']['r'].update(current='a',deadline=10,locked=['b'])
    data=wav();encoded=base64.b64encode(data).decode();action=event('audio',user_id='a',server_time=9,packet_id='packet',audio_base64=encoded)
    out=ok(call(state,action));assert out['result']['recipients']==['b','c'];assert base64.b64decode(out['result']['audio_base64'])==data
    replay=ok(call(out,action));assert replay['result']['recipients']==[]
    for extra in [{'user_id':'b'},{'server_time':10},{'server_time':True},{'server_time':float('nan')},{'packet_id':''},{'audio_base64':'not base64'},{'audio_base64':base64.b64encode(data[:-4]).decode()},{'audio_base64':base64.b64encode(wav(rate=16000)).decode()},{'audio_base64':base64.b64encode(wav(channels=2)).decode()},{'audio_base64':base64.b64encode(wav(samples=0)).decode()}]:denied(state,{**action,**extra})
    denied(out,{**action,'audio_base64':base64.b64encode(wav(samples=201)).decode()})
    changed=copy.deepcopy(out);changed['rooms']['r'].update(current='c',deadline=20);denied(changed,{**action,'user_id':'c','server_time':11})
    with App() as app:
        app.setup();packet=event('audio',user_id='speaker',server_time=101,packet_id='wire',audio_base64=encoded)
        app.post(packet)
        for user in ['listener','locked']:
            messages=app.inbox(user);assert len(messages)==1 and messages[0]['packet_id']=='wire';assert base64.b64decode(messages[0]['audio_base64'])==data;assert app.inbox(user)==[]
        assert app.inbox('speaker')==[] and app.inbox('listener','other-room')==[]
        app.post(packet);assert app.inbox('listener')==[]
        app.post({**packet,'packet_id':'late','server_time':160},400);assert app.inbox('listener')==[]
        large=wav(samples=(1048576-44)//2);assert len(large)==1048576
        app.post({**packet,'packet_id':'max','audio_base64':base64.b64encode(large).decode()});assert base64.b64decode(app.inbox('listener')[0]['audio_base64'])==large
        app.post({**packet,'packet_id':'oversize','audio_base64':base64.b64encode(wav(samples=(1048576-44)//2+1)).decode()},400);assert app.inbox('listener')==[]
