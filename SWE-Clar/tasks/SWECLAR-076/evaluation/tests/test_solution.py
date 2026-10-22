from copy import deepcopy
import math
from candidate_proxy import call,browser

def base():
 a={'a':{'position':{'x':2.7,'y':0,'z':0},'velocity':{'x':.6,'y':.15,'z':.1}}}
 return {'timestamp':0,'mode':'room','lives':2,'initial_lives':2,'portals':{'p':{'active':True}},'asteroids':a,'level_asteroids':deepcopy(a),'weapons':{'g1':{'power':2},'g2':{'power':3},'g3':{'power':1}},'equipped':[],'shield_energy':0,'wave':0,'enemies':{},'events':[],'restart_count':0}
def same(a,b):
 for k in base():assert a.get(k)==b.get(k),k
def event(s,kind,**kw):return {'type':kind,'timestamp':s.get('timestamp',0)+1,**kw}
def ok(s,kind,**kw):
 out=call(s,event(s,kind,**kw));assert 'error' not in out,out;return out
def denied(s,kind,**kw):
 out=call(s,event(s,kind,**kw));assert out.get('error',{}).get('code');same(out,s);return out
def click(selector,**kw):return {'op':'click','selector':selector,**kw}

def assert_transient(rows):
 # Compare the same post-action gameplay state while its effect is visible and
 # after it expires. Neither movement nor a permanent HP/color change suffices.
 active,settled=rows[-2:]
 assert active['state']==settled['state']
 assert active['canvas']!=settled['canvas'],'Missing transient scene effect'

def test_ru_001_time_entry():
 s=base();s=ok(s,'transition',portal_id='p',target_mode='cockpit',timestamp=10);assert s['timestamp']==10
 denied(s,'transition',portal_id='p',target_mode='room',timestamp=9)
 out=ok(s,'transition',portal_id='p',target_mode='room',timestamp=10);assert out['timestamp']==10
 for stamp in [True,float('inf'),'20']:denied(s,'transition',portal_id='p',target_mode='room',timestamp=stamp)
 denied(s,'unknown');r=browser(base(),[{'op':'inspect'}])[0];assert r['webgl']['present'] and r['webgl']['depth']

def test_ru_002_portal():
 s=base();s['lives']=1;out=ok(s,'transition',portal_id='p',target_mode='cockpit');assert out['mode']=='cockpit' and out['lives']==out['result']['lives']==1;assert out['result']['mode']=='cockpit';out=ok(out,'transition',portal_id='p',target_mode='room');assert out['mode']=='room' and out['lives']==1
 for portal,mode in [('missing','cockpit'),('p','invalid'),('p','room')]:denied(s,'transition',portal_id=portal,target_mode=mode)
 s['portals']['p']['active']=False;denied(s,'transition',portal_id='p',target_mode='cockpit')
 r=browser(base(),[{'op':'inspect'},click('#portal'),click('#portal')]);assert r[1]['state']['mode']=='cockpit' and r[2]['state']['mode']=='room';assert r[0]['canvas']!=r[1]['canvas'];assert all(x['state']['lives']==2 for x in r)

def test_ru_003_physics_ripple():
 s=base();s['asteroids']['a']={'position':{'x':1,'y':-1,'z':1},'velocity':{'x':2,'y':-2,'z':1}};bounds={'x':2,'y':2,'z':2};out=ok(s,'move_asteroid',asteroid_id='a',bounds=bounds,through_portal=True,angle=37);r=out['result'];assert r['position']=={'x':2,'y':-2,'z':2} and r['velocity']=={'x':-2,'y':2,'z':1};assert all(out['events'][-1][k]==v for k,v in {'type':'portal_ripple','asteroid_id':'a','angle':37}.items())
 plain=ok(s,'move_asteroid',asteroid_id='a',bounds=bounds);assert plain['events']==[]
 still=base();still['asteroids']['a']['velocity']=dict.fromkeys(('x','y','z'),0)
 assert_transient(browser(still,[click('#ripple'),{'op':'wait','milliseconds':1200}],controlled_clock=True))
 denied(s,'move_asteroid',asteroid_id='missing',bounds=bounds);denied(s,'move_asteroid',asteroid_id='a',bounds={**bounds,'y':0})
 r=browser(base(),[{'op':'inspect'},click('#step'),click('#step'),click('#ripple'),click('#play'),click('#play',response=False)]);assert r[1]['state']['asteroids']['a']['position']['x']==3 and r[1]['state']['asteroids']['a']['velocity']['x']<0;assert math.isclose(r[2]['state']['asteroids']['a']['position']['x'],2.4);assert r[0]['canvas']!=r[1]['canvas'];assert r[3]['state']['events'][-1]['type']=='portal_ripple';assert r[4]['state']['timestamp']>r[3]['state']['timestamp']

def test_ru_004_combat():
 s=base();s=ok(s,'equip',weapon_id='g1');s=ok(s,'equip',weapon_id='g2')
 for weapon in ['g1','g3','missing']:denied(s,'equip',weapon_id=weapon)
 shield=ok(s,'activate_shield',energy=4);out=ok(shield,'hit',damage=6);assert all(out['result'][k]==v for k,v in {'absorbed':4,'lives':1,'shield_energy':0}.items());zero=ok(shield,'hit',damage=0);assert zero['lives']==2 and zero['shield_energy']==4
 denied(s,'activate_shield',energy=-1);denied(s,'hit',damage=True)
 s['enemies']={'e':{'hp':3,'position':{'x':0,'y':.5,'z':-1}}};denied(s,'fire',weapon_id='g3',enemy_id='e');out=ok(s,'fire',weapon_id='g1',enemy_id='e');assert out['enemies']['e']['hp']==1;out=ok(out,'fire',weapon_id='g1',enemy_id='e');assert out['enemies']['e']['hp']==0;denied(out,'fire',weapon_id='g1',enemy_id='e')
 assert_transient(browser(s,[click('#fire'),{'op':'wait','milliseconds':1200}],controlled_clock=True))
 # Each successful shot appends exactly one event and preserves prior history.
 seeded=deepcopy(s);seeded['events']=[{'type':'existing','marker':'keep'}]
 for weapon in ['g1','g2']:
  fired=ok(seeded,'fire',weapon_id=weapon,enemy_id='e')
  assert fired['events'][:-1]==seeded['events'] and len(fired['events'])==len(seeded['events'])+1
  assert all(fired['events'][-1].get(k)==v for k,v in {'type':'shot','weapon_id':weapon,'enemy_id':'e'}.items())
 initial=base();initial['enemies']=deepcopy(s['enemies']);r=browser(initial,[{'op':'inspect'},click('#equip'),click('#fire'),click('#fire'),click('#activate'),click('#hit'),click('#hit')]);assert r[2]['state']['enemies']['e']['hp']==1 and r[3]['state']['enemies']['e']['hp']==0;assert r[0]['canvas']!=r[3]['canvas'];assert r[4]['canvas']!=r[3]['canvas'];assert r[5]['state']['shield_energy']==1 and r[6]['state']['lives']==1

def test_ru_005_waves_restart():
 s=ok(base(),'spawn_wave',wave=1);assert s['result']['count']==2 and s['result']['health']==2 and len(s['enemies'])==2
 out=ok(s,'spawn_wave',wave=3);assert out['result']['count']>s['result']['count'] and out['result']['health']>s['result']['health'];assert all(x['hp']==4 for x in out['enemies'].values());denied(out,'spawn_wave',wave=3);denied(out,'spawn_wave',wave=True)
 out['lives']=1;out['mode']='cockpit';out['equipped']=['g1'];out['asteroids']['a']['position']['x']=0;r=ok(out,'hit',damage=100);assert r['lives']==r['result']['lives']==2 and r['restart_count']==1 and r['shield_energy']==0;assert r['mode']=='cockpit' and r['equipped']==['g1'] and r['wave']==3;assert r['asteroids']==r['level_asteroids'];assert len(r['enemies'])==4 and all(e['hp']==4 for e in r['enemies'].values());assert r['events'][-1]['type']=='level_restart'
 ui=browser(base(),[click('#spawn'),click('#spawn'),click('#step'),click('#hit'),click('#hit')]);assert len(ui[0]['state']['enemies'])==2 and len(ui[1]['state']['enemies'])==3;assert ui[3]['state']['lives']==1 and ui[4]['state']['lives']==2 and ui[4]['state']['restart_count']==1;assert 'Restarts 1' in ui[4]['hud'];assert ui[4]['state']['asteroids']==ui[4]['state']['level_asteroids']
