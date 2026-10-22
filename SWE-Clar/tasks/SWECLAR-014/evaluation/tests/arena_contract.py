"""Private behavior oracles for actual multiplayer HTTP and rendered browser UI."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import traceback
sys.path.insert(0, '/public_tests')
from arena_support import Application, CandidateFailure, browser_session, request
from playwright.sync_api import expect, TimeoutError as BrowserTimeout

NOW = 300000


class PrerequisiteFailure(CandidateFailure):
    def __init__(self, ru, message):
        self.ru = ru
        super().__init__(message)


class Checks:
    def __init__(self): self.passed = []
    def require(self, value, name):
        if not value: raise CandidateFailure(name)
        self.passed.append(name)


def fixture():
    return {'rooms': [
        {'id':'meadow','label':'Synthetic Meadow Arena','cols':12,'rows':8,
         'walls':[[2,2],[7,3],[7,4]],'spawn_points':[[2,3],[4,3],[2,6],[4,6]]},
        {'id':'harbor','label':'Synthetic Harbor Arena','cols':10,'rows':8,
         'walls':[[5,4]],'spawn_points':[[2,3],[4,3]]}]}


class Case:
    def __init__(self,c): self.c=c; self.app=Application(world=fixture(),now_ms=NOW); self.n=0
    def __enter__(self): self.app.__enter__(); return self
    def __exit__(self,*args): self.app.__exit__(*args)
    def call(self,path,body=None,actor=None,status=200,prerequisite=None):
        r=request(self.app,path,body,actor['token'] if actor else None)
        if r['status']!=status and prerequisite: raise PrerequisiteFailure(prerequisite,path+': '+json.dumps(r))
        self.c.require(r['status']==status,path+' status '+str(status))
        return r['body']
    def join(self,label='Synthetic Player',room='meadow',**extra):
        return self.call('/api/join',{'room_id':room,'label':label,**extra},status=201,prerequisite='RU-001')
    def state(self,a): return self.call('/api/state',actor=a,prerequisite='RU-001')['state']
    def player(self,state,a): return next(p for p in state['players'] if p['id']==a['player_id'])
    def move(self,a,direction,command=None,generation=1,status=200,**extra):
        self.n+=1
        return self.call('/api/move',{'generation':generation,'command_id':command or 'intent_'+str(self.n),'direction':direction,**extra},a,status)
    def kill(self,a):
        self.app.set_clock(NOW+7000)
        self.move(a,'right')
        for _ in range(3): self.move(a,'right')
        self.c.require(not self.player(self.state(a),a)['alive'],'Contact prerequisite creates a dead player')
    def ui_join(self,page,label='Synthetic Browser Player'):
        page.goto(self.app.url);page.locator('#room-select').select_option('meadow');page.locator('#player-label').fill(label)
        with page.expect_response('**/api/join') as response: page.locator('#join').click()
        payload=response.value.json()
        if response.value.status!=201: raise PrerequisiteFailure('RU-001','Browser join failed')
        expect(page.locator('#roster')).to_contain_text(label)
        return payload


def gate_one(c):
    with Case(c) as x:
        x.call('/api/state',status=401)
        r=request(x.app,'/api/state',token='fabricated-token');c.require(r['status']==401,'Forged bearer token denied')
        x.call('/api/join',{'room_id':'unknown','label':'Synthetic'},status=404)
        for label in ['', ' '*3, 'x'*41, None, 7]: x.call('/api/join',{'room_id':'meadow','label':label},status=400)
        a=x.join('Synthetic <b>literal</b>',x=99,y=-1,hp=900,generation=90,spawn_ms=0,protected_until_ms=1)
        b=x.join('Synthetic Other');other=x.join('Synthetic Foreign',room='harbor')
        p=x.player(a['state'],a)
        c.require((p['x'],p['y'],p['hp'],p['generation'],p['spawn_ms'],p['alive'])==(2,3,3,1,NOW,True),'Joining uses server coordinates, health, generation and time')
        room=x.call('/api/state?room_id=meadow&player_id='+a['player_id'],actor=other)['state']
        c.require(room['room']['id']=='harbor' and [p['id'] for p in room['players']]==[other['player_id']],'Query cannot widen room access')
        tokens=[a['token'],b['token'],other['token']]
        c.require(len(set(tokens))==3 and all(isinstance(t,str) and len(t)>=32 for t in tokens),'Independent opaque session tokens')
        for value in [x.call('/api/rooms'),x.state(a),room]: c.require(not any(t in json.dumps(value) for t in tokens),'No session token in observable game state')
        seq=[x.state(a)['seq'],x.state(other)['seq'],x.state(b)['seq']]
        c.require(all(type(n)is int for n in seq) and seq[0]<seq[1]<seq[2],'Process-wide state sequence strictly increases')
        x.join('Third');x.join('Fourth');x.call('/api/join',{'room_id':'meadow','label':'Full room'},status=409)
        c.require(len(x.state(a)['players'])==4,'Full spawn area does not create an extra player')
        x.call('/api/leave',{},a);x.call('/api/state',actor=a,status=401)
        c.require(len(x.state(b)['players'])==3 and len(x.state(other)['players'])==1,'Leave changes only its own room/session')
    with Case(c) as x,browser_session() as browser:
        context=browser.new_context(viewport={'width':390,'height':844});one=context.new_page();two=context.new_page()
        a=x.ui_join(one,'Synthetic <b>literal</b>');b=x.ui_join(two,'Synthetic Observer')
        expect(one.locator('#roster [data-player-id]')).to_have_count(2)
        c.require(one.locator('#roster b').count()==0,'Player label stays literal in real DOM')
        fresh=context.new_page();fresh.goto(x.app.url);expect(fresh.locator('#join-form')).to_be_visible();fresh.close()
        c.require(one.evaluate('(tokens)=>![localStorage,sessionStorage].some(s=>Object.keys(s).some(k=>tokens.some(t=>s.getItem(k).includes(t))))',[a['token'],b['token']]),'Session tokens are not persisted in browser storage')
        before=two.locator('#arena').screenshot()
        source=cell_pixels(two,2,3);destination=cell_pixels(two,2,4)
        for wx,wy in fixture()['rooms'][0]['walls']:
            c.require(cell_pixels(two,wx,wy)!=cell_pixels(two,0,0),'Wall rendered in its actual board cell')
        one.locator('[data-direction="down"]').click();one.wait_for_timeout(350)
        state=x.state(a);c.require(x.player(state,a)['y']==4,'Real browser movement reaches server')
        c.require(two.locator('#arena').screenshot()!=before,'Another browser draws the changed world')
        c.require(cell_pixels(two,2,3)!=source and cell_pixels(two,2,4)!=destination,'Movement changes both vacated and entered cell pixels')
        for width,height in [(390,844),(1280,900)]:
            one.set_viewport_size({'width':width,'height':height});c.require(one.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Responsive canvas viewport '+str(width))
        one.locator('#leave').click();expect(one.locator('#join-form')).to_be_visible()
        c.require(one.locator('#roster').inner_text()=='','Leave clears rendered identities')
        x.call('/api/leave',{},b);expect(two.locator('#join-form')).to_be_visible()
        c.require(two.locator('#roster').inner_text()=='','401 clears rendered room state')
        context.close()


def gate_two(c):
    with Case(c) as x:
        a=x.join('Synthetic mover');b=x.join('Synthetic obstacle')
        x.app.set_clock(max(NOW+1,max(p['protected_until_ms'] for p in x.state(a)['players'])+1))
        for direction in ['invalid',None,True]: x.move(a,direction,status=400)
        x.move(a,'up',generation=True,status=400)
        for key in ['','bad key','x'*65]: x.move(a,'up',command=key if key else None,status=400) if key else x.call('/api/move',{'direction':'up','generation':1,'command_id':''},a,400)
        x.move(a,'up');p=x.player(x.state(a),a);c.require((p['x'],p['y'],p['hp'])==(2,3,3),'Wall collision blocks without damage')
        for _ in range(4):x.move(a,'left')
        p=x.player(x.state(a),a);c.require((p['x'],p['hp'])==(0,3),'Outside board behaves as a wall')
        for _ in range(3):x.move(a,'right',player_id=b['player_id'],room_id='harbor',x=99,hp=99)
        for _ in range(3):x.move(a,'right')
        state=x.state(a);p=x.player(state,a);q=x.player(state,b)
        c.require((p['x'],p['hp'],p['alive'])==(3,0,False) and (q['x'],q['hp'])==(4,3),'Normal contact damages only the mover and produces death')
        x.move(b,'left');q=x.player(x.state(b),b);c.require((q['x'],q['hp'])==(3,3),'Dead body does not occupy a cell')
        before=x.state(b)['players'];x.app.set_clock(NOW+100000)
        c.require(x.state(b)['players']==before,'Polling and time do not move/harm/respawn players')
    with Case(c) as x:
        a=x.join();b=x.join('Synthetic second');x.app.set_clock(NOW+7000)
        requests=[(a,'right'),(b,'left')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda item:request(x.app,'/api/move',{'generation':1,'command_id':'simultaneous','direction':item[1]},item[0]['token']),requests))
        c.require(all(r['status']==200 for r in results),'Concurrent movement completes')
        players=x.state(a)['players'];c.require(sorted(p['hp'] for p in players)==[2,3] and len({(p['x'],p['y']) for p in players})==2,'Concurrent same-cell moves follow a legal serial order')


def gate_three(c):
    with Case(c) as x:
        a=x.join(spawn_ms=0,protected_until_ms=999999999);b=x.join('Synthetic other')
        for actor in [a,b]:
            p=x.player(x.state(actor),actor);c.require(p['spawn_ms']==NOW and p['protected_until_ms']==NOW+6000,'Exactly six seconds assigned by server')
        x.move(a,'up');c.require(x.player(x.state(a),a)['y']==3,'Protection does not bypass walls')
        x.app.set_clock(NOW+5999);x.move(a,'right');x.move(a,'right')
        players=x.state(a)['players'];c.require(all(p['hp']==3 and p['x']==4 for p in players),'Protected overlap causes neither damage nor blocking')
        x.app.set_clock(NOW+6000);c.require(x.state(a)['players']==players,'Expiry does not retroactively harm or move overlapping players')
        x.move(a,'left');x.move(a,'right',protected=True,protected_until_ms=999999999,server_now_ms=0)
        p=x.player(x.state(a),a);c.require((p['x'],p['hp'])==(3,2),'Equality deadline restores collision despite forged client fields')
    for moving_protected in [False,True]:
        with Case(c) as x:
            a=x.join();x.app.set_clock(NOW+3000);b=x.join('Later protected player');x.app.set_clock(NOW+6000)
            if moving_protected:
                x.move(b,'left');x.move(b,'left');p=x.player(x.state(b),b);c.require((p['x'],p['hp'])==(2,3),'Protected mover passes through unprotected stationary player')
            else:
                x.move(a,'right');x.move(a,'right');p=x.player(x.state(a),a);c.require((p['x'],p['hp'])==(4,3),'Unprotected mover passes through protected stationary player')


def cell_pixels(page,x,y):
    return page.locator('#arena').evaluate('(canvas,p)=>Array.from(canvas.getContext("2d").getImageData(p.x*24+2,p.y*24+2,20,20).data)',{'x':x,'y':y})


def timer_interface(c):
    with Case(c) as x,browser_session() as browser:
        page=browser.new_page();page.goto(x.app.url)
        result=page.evaluate("""async () => {
          const {ArenaClient}=await import('/app.js'); const c=new ArenaClient();
          let clock=100; const original=performance.now.bind(performance);performance.now=()=>clock;
          try {
            await c.join('meadow','Synthetic Timing Probe');const first=structuredClone(c.state),id=c.playerId;
            const checks=[];
            clock+=2001;
            const fresh=structuredClone(first);fresh.seq+=100;fresh.server_now_ms+=2001;
            c.acceptState(fresh);checks.push(c.state.seq===fresh.seq);
            for(const seq of [fresh.seq,fresh.seq-1]) {
              const stale=structuredClone(first);stale.seq=seq;stale.players.find(p=>p.id===id).x=9;
              c.acceptState(stale);checks.push(c.state.players.find(p=>p.id===id).x===2 && c.state.seq===fresh.seq);
            }
            await c.leave();checks.push(c.state===null && c.playerId===null);
            return checks;
          } finally {performance.now=original;c.dispose();}
        }""")
        c.require(all(result),'Public response path ignores duplicate/old sequence; leave clears controller')
        page.close()


def gate_four(c):
    timer_interface(c)
    with Case(c) as x,browser_session() as browser:
        page=browser.new_page(viewport={'width':390,'height':844})
        page.add_init_script('Date.now = () => 9000000000000;')
        a=x.ui_join(page);old=a['state']
        first=int(page.locator('#shield-remaining').inner_text());c.require(5<=first<=6,'Initial visible seconds use server clock rather than skewed wall clock')
        before=page.locator('#arena').screenshot();page.wait_for_timeout(1250)
        later=int(page.locator('#shield-remaining').inner_text());c.require(0<later<first,'Countdown advances despite newer delayed fixed-clock snapshots')
        page.locator('[data-direction="down"]').click();page.wait_for_timeout(250)
        current=x.player(x.state(a),a);c.require(current['y']==4,'Actual movement prerequisite for stale visual check')
        x.app.set_clock(NOW+5500);expect(page.locator('#shield-remaining')).to_have_text('1',timeout=3000)
        current_picture=page.locator('#arena').screenshot()
        protected_body=cell_pixels(page,2,4)
        page.route('**/api/state',lambda route:route.fulfill(status=200,json={'state':old}))
        page.wait_for_timeout(750)
        expect(page.locator('#shield-remaining')).to_have_text('0');expect(page.locator('#shield-indicator')).to_be_hidden()
        expired=page.locator('#arena').screenshot()
        c.require(expired!=current_picture and expired!=before,'Actual canvas updates protection appearance without accepting old position/timer')
        c.require(cell_pixels(page,2,4)!=protected_body,'Protection changes the actual body cell, not only a global counter')
        # Zero remains stable while many old responses arrive.
        page.wait_for_timeout(450);c.require(page.locator('#shield-remaining').inner_text()=='0','Old snapshots cannot restart protection')
        page.unroute('**/api/state');page.close()


def gate_five(c):
    with Case(c) as x:
        a=x.join();b=x.join('Synthetic obstacle')
        x.call('/api/respawn',{'generation':1,'command_id':'early'},a,409)
        x.app.set_clock(NOW+7000)
        command={'generation':1,'command_id':'first','direction':'right'}
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:request(x.app,'/api/move',command,a['token']),range(6)))
        c.require(all(r['status']==200 for r in results),'Duplicate commands return success/replay')
        p=x.player(x.state(a),a);c.require((p['x'],p['hp'])==(3,3),'Concurrent duplicate movement commits once')
        x.call('/api/move',{**command,'direction':'left'},a,409)
        x.call('/api/respawn',{'generation':1,'command_id':'first'},a,409)
        for _ in range(3):x.move(a,'right')
        c.require(not x.player(x.state(a),a)['alive'],'Dead player prerequisite')
        x.call('/api/respawn',{'generation':1,'command_id':'first'},a,409)
        body={'generation':1,'command_id':'early'}
        created=x.call('/api/respawn',body,a,prerequisite='RU-005')['state'];p=x.player(created,a)
        c.require((p['generation'],p['hp'],p['alive'],p['spawn_ms'],p['protected_until_ms'])==(2,3,True,NOW+7000,NOW+13000),'Rejected key remains reusable and successful respawn resets incarnation')
        x.move(a,'down',generation=2)
        replay=x.call('/api/respawn',body,a)['state'];c.require(x.player(replay,a)['y']==4 and x.player(replay,a)['generation']==2,'Respawn replay returns current position without respawning again')
        x.move(a,'left',generation=1,status=409)
        x.call('/api/respawn',{'generation':True,'command_id':'invalid'},a,400)
        x.call('/api/respawn',{'generation':2,'command_id':'live'},a,409)
    with Case(c) as x:
        a=x.join();b=x.join('Synthetic obstacle');x.kill(a)
        # All pads can be occupied while a dead player remains in the room.
        extras=[x.join('Synthetic blocker '+str(i)) for i in range(3)]
        body={'generation':1,'command_id':'full_retry'};before=x.state(a)['players']
        x.call('/api/respawn',body,a,409)
        c.require(x.state(a)['players']==before,'Full spawn conflict is mutation-free')
        x.call('/api/leave',{},extras[0])
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:request(x.app,'/api/respawn',body,a['token']),range(4)))
        c.require(all(r['status']==200 for r in replies),'Concurrent respawn replay succeeds after rejected full-area attempt')
        p=x.player(x.state(a),a);c.require((p['generation'],p['x'],p['y'])==(2,2,3),'Concurrent respawn selects first freed pad and increments once')
        x.app.set_clock(NOW+14000)
        x.move(a,'right',generation=2)
        for _ in range(3):x.move(a,'right',generation=2)
        x.call('/api/respawn',{'generation':2,'command_id':'next_life'},a)
        x.call('/api/respawn',body,a,409)
        c.require(x.player(x.state(a),a)['generation']==3,'Very old respawn cannot reset a later generation')
    with Case(c) as x:
        a=x.join();b=x.join('Other actor');x.app.set_clock(NOW+7000)
        x.move(a,'down',command='same_key');x.move(b,'down',command='same_key')
        c.require(all(p['y']==4 for p in x.state(a)['players']),'Different actors use the same key independently')
    with Case(c) as x,browser_session() as browser:
        page=browser.new_page();a=x.ui_join(page);b=x.join('Synthetic obstacle');x.app.set_clock(NOW+7000)
        requests=[]
        def lose_once(route):
            requests.append(route.request.post_data_json)
            if len(requests)==1: route.fetch();route.abort()
            else: route.continue_()
        page.route('**/api/move',lose_once)
        page.locator('[data-direction="down"]').click();expect(page.locator('#error')).to_be_visible()
        page.locator('[data-direction="down"]').click();expect(page.locator('#error')).to_be_hidden()
        c.require(len(requests)==2 and requests[0]==requests[1] and x.player(x.state(a),a)['y']==4,'Lost move response retry preserves original intent and moves once')
        page.unroute('**/api/move');held=[]
        page.route('**/api/move',lambda route:held.append(route))
        button=page.locator('[data-direction="up"]');box=button.bounding_box();button.click();page.wait_for_timeout(100)
        page.mouse.click(box['x']+box['width']/2,box['y']+box['height']/2)
        c.require(len(held)==1,'Pending double click produces one movement request')
        response=held[0].fetch();held[0].fulfill(response=response);page.unroute('**/api/move');page.wait_for_timeout(250)
        c.require(x.player(x.state(a),a)['y']==3,'Held request commits one movement')
        # Kill via real commands, then exercise actual UI respawn with a lost reply.
        vacant=cell_pixels(page,3,3)
        x.move(a,'right');page.wait_for_timeout(350);living=cell_pixels(page,3,3)
        c.require(living!=vacant,'Live body appears in entered cell before contact')
        for _ in range(3):x.move(a,'right')
        expect(page.locator('#respawn')).to_be_enabled();page.wait_for_timeout(350)
        c.require(cell_pixels(page,3,3)==vacant,'Dead body disappears from the occupied board cell')
        respawns=[]
        def lose_respawn(route):
            respawns.append(route.request.post_data_json)
            if len(respawns)==1:route.fetch();route.abort()
            else:route.continue_()
        page.route('**/api/respawn',lose_respawn)
        page.locator('#respawn').click();expect(page.locator('#error')).to_be_visible()
        page.wait_for_timeout(250)
        if page.locator('#respawn').is_enabled():
            page.locator('#respawn').click();expect(page.locator('#error')).to_be_hidden()
            c.require(len(respawns)==2 and respawns[0]==respawns[1],'Lost respawn retry retains original generation and command')
        else:
            c.require(len(respawns)==1 and x.player(x.state(a),a)['generation']==2,'Lost respawn is reconciled by an authoritative poll without duplicate command')
        p=x.player(x.state(a),a);c.require(p['generation']==2 and p['hp']==3,'UI respawn commits one new generation')
        c.require(0<int(page.locator('#shield-remaining').inner_text())<=6,'New generation resets real visible countdown')
        page.close()

    with Case(c) as x,browser_session() as browser:
        page=browser.new_page();page.goto(x.app.url)
        page.evaluate("async()=>{const {ArenaClient}=await import('/app.js');window.probe=new ArenaClient();await probe.join('meadow','Synthetic Retry Probe');}")
        attempts=[]
        def reject_first(route):
            attempts.append(route.request.post_data_json)
            if len(attempts)==1:route.abort()
            else:route.continue_()
        page.route('**/api/move',reject_first)
        page.evaluate("async()=>{await probe.move('down');await probe.move('right');}")
        c.require(len(attempts)==2 and attempts[0]['command_id']!=attempts[1]['command_id'],'Explicitly different action abandons a failed intent')
        page.unroute('**/api/move');held=[];moves=[]
        page.route('**/api/state',lambda route:held.append(route))
        def conflict(route):
            moves.append(route.request.post_data_json);route.fulfill(status=409,json={'error':'conflict'})
        page.route('**/api/move',conflict)
        page.evaluate("()=>{window.pending=probe.move('down');}");page.wait_for_timeout(150)
        c.require(len(held)==1,'Conflict requests authoritative refresh')
        # Observe requests while refresh is held, without awaiting an action
        # which may legitimately queue behind that refresh.
        page.evaluate("()=>{window.followup=probe.move('left');}")
        page.wait_for_timeout(150)
        c.require(len(moves)==1,'Conflict refresh finishes before another intent is accepted')
        # A queued action can itself receive a conflict and request another
        # refresh. Release interception before allowing either action to settle.
        page.unroute('**/api/state');held[0].continue_()
        page.evaluate("()=>{window.actionsSettled=false;window.actionResults=null;Promise.allSettled([window.pending,window.followup]).then(r=>{window.actionResults=r.map(x=>x.status);window.actionsSettled=true;});}")
        page.wait_for_function('window.actionsSettled',timeout=10000)
        c.require(page.evaluate("window.actionResults.every(x=>x==='fulfilled')"),'Conflict actions settle after authoritative refresh')
        page.unroute('**/api/move')
        c.require(page.evaluate('Boolean(probe.error)'),'Conflict ends with visible controller error and released action lock')
        # A completed old request delayed across Leave/Join cannot restore old state.
        delayed=[]
        def delay_reply(route):delayed.append((route,route.fetch()))
        page.route('**/api/move',delay_reply);page.evaluate("()=>{window.oldPending=probe.move('down');}");page.wait_for_timeout(150)
        c.require(len(delayed)==1,'Old command response held independently')
        page.evaluate("async()=>{await probe.leave();await probe.join('harbor','Synthetic New Session');}")
        new_id=page.evaluate('probe.playerId');delayed[0][0].fulfill(response=delayed[0][1]);page.evaluate('()=>oldPending')
        c.require(page.evaluate('probe.state.room.id')=='harbor' and page.evaluate('probe.playerId')==new_id,'Late old-session command cannot restore previous room or actor')
        page.evaluate('()=>probe.dispose()');page.close()


GATES=[gate_one,gate_two,gate_three,gate_four,gate_five]


def main():
    results=[];errors=[]
    for i,gate in enumerate(GATES,1):
        c=Checks();row={'ru_id':f'RU-{i:03d}','passed':False}
        try:gate(c);row.update(passed=True,detail='All executable checks passed')
        except PrerequisiteFailure as exc:row.update(detail=str(exc),prerequisite_failure=exc.ru)
        except (AssertionError,KeyError,TypeError,IndexError,StopIteration,BrowserTimeout) as exc:row['detail']=type(exc).__name__+': '+str(exc)
        except Exception as exc:
            row['detail']='Environment/evaluator failure: '+repr(exc);errors.append({'ru_id':row['ru_id'],'traceback':traceback.format_exc()})
        row['checks_passed']=c.passed;results.append(row)
    print(json.dumps({'harness_ok':not errors,'results':results,'infrastructure_errors':errors}))
    return 0 if not errors else 2


if __name__=='__main__':raise SystemExit(main())
