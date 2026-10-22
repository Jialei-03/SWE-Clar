from copy import deepcopy
from collections import Counter
from candidate_proxy import call,browser

def base():return {'combatants':{'player':{'hp':20,'level':2,'defense':1},'enemy':{'hp':12,'level':1,'defense':2}},'skills':{'strike':{'power':6}},'inventories':{'player':{'capacity':4,'slots':[]},'other':{'capacity':2,'slots':[]}},'creatures':{'player':['ember','moss']},'recipes':{'stone':{'level':1,'inputs':['ember','moss'],'result':'stone'}},'drops':{},'events':[]}
def act(s,kind,**a):return call(s,{'type':kind,**a})
def state(s):return {k:s.get(k,{} if k!='events' else []) for k in ['combatants','skills','inventories','creatures','recipes','drops','events']}
def denied(before,out):
 import json
 assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
 # JSON round trips create fresh NaN objects, which are not equal to themselves.
 assert json.dumps(state(out),sort_keys=True)==json.dumps(state(before),sort_keys=True)
def pairs(s,uid='player'):return sorted((x['item_id'],x['quantity']) for x in s['inventories'][uid]['slots'])
def available(s,did):return did in s['drops'] and not s['drops'][did].get('picked') and not s['drops'][did].get('expired')
def item():return {'item_id':'fragment','stackable':True,'stack_limit':3}
def drop(s=None,now=0,did='d'):
 s=deepcopy(s or base());s['combatants']['enemy']['hp']=0
 return act(s,'roll_drop',enemy_id='enemy',drop_id=did,roll=0,chance=1,owner_id='player',now=now,item=item())

def test_ru_001_http_canvas_movement_and_rejection():
 s=base();denied(s,act(s,'unknown'));a={'type':'use_skill','source_id':'player','target_id':'enemy','skill_id':'strike'};call(s,a)
 rows=browser(s,[{'op':'inspect'},{'op':'move','key':'ArrowRight'},{'op':'http','path':'/action','method':'POST','data':[]},{'op':'http','path':'/health'}])
 assert rows[0]['canvas']!=rows[1]['canvas'];assert rows[2]['response_status']==400 and state(rows[2]['state'])==state(s);assert rows[3]['response_status']==200 and rows[3]['response']['ok']

def combat_numeric_guards():
 for bad in [True,False,float('nan'),float('inf'),-float('inf'),'2']:
  for collection,record,field in [('combatants',who,field) for who in ['player','enemy'] for field in ['hp','level','defense']]+[('skills','strike','power')]:
   invalid=base();invalid[collection][record][field]=bad
   denied(invalid,act(invalid,'use_skill',source_id='player',target_id='enemy',skill_id='strike'))

def test_ru_002_damage_events_and_actual_health_scene():
 combat_numeric_guards()
 s=base();s['combatants']['enemy']['hp']=3
 out=act(s,'use_skill',source_id='player',target_id='enemy',skill_id='strike');assert out['result']['damage']==6 and out['result']['target_hp']==0 and len(out['events'])==1;assert out['combatants']['player']==s['combatants']['player']
 denied(out,act(out,'use_skill',source_id='player',target_id='enemy',skill_id='strike'))
 for kind in ['source','target','skill']:
  fields={'source_id':'player','target_id':'enemy','skill_id':'strike'};fields[{'source':'source_id','target':'target_id','skill':'skill_id'}[kind]]='absent';denied(s,act(s,'use_skill',**fields))
 zero=base();zero['skills']['strike']['power']=-10;out=act(zero,'use_skill',source_id='player',target_id='enemy',skill_id='strike');assert out['result']['damage']==0 and out['result']['target_hp']==12 and len(out['events'])==1
 dead=base();dead['combatants']['player']['hp']=0;denied(dead,act(dead,'use_skill',source_id='player',target_id='enemy',skill_id='strike'))
 rows=browser(base(),[{'op':'inspect'},{'op':'click','selector':'#attack','response':'/action'}]);assert rows[1]['state']['combatants']['enemy']['hp']==6 and rows[0]['canvas']!=rows[1]['canvas'];assert 'damage' in rows[1]['text']

def test_ru_003_inventory_atomic_stacks_and_panel():
 s=base();s['inventories']['player']['capacity']=2
 first=act(s,'add_item',user_id='player',item=item(),quantity=4);assert pairs(first)==[('fragment',1),('fragment',3)]
 filled=act(first,'add_item',user_id='player',item=item(),quantity=2);assert pairs(filled)==[('fragment',3),('fragment',3)]
 denied(filled,act(filled,'add_item',user_id='player',item=item(),quantity=1))
 for q in [0,-1,True,1.5,'2']:denied(s,act(s,'add_item',user_id='player',item=item(),quantity=q))
 denied(s,act(s,'add_item',user_id='missing',item=item(),quantity=1));denied(s,act(s,'add_item',user_id='player',item={**item(),'stack_limit':0},quantity=1))
 plain={'item_id':'tool','stackable':False};separate=act(s,'add_item',user_id='player',item=plain,quantity=2);assert pairs(separate)==[('tool',1),('tool',1)]
 partially=act(s,'add_item',user_id='player',item=plain,quantity=1);denied(partially,act(partially,'add_item',user_id='player',item=plain,quantity=2))
 rows=browser(s,[{'op':'http','path':'/action','method':'POST','data':{'type':'add_item','user_id':'player','item':item(),'quantity':4}},{'op':'reload'}]);assert pairs(rows[-1]['state'])==[('fragment',1),('fragment',3)] and 'fragment' in rows[-1]['inventory']

def loot_numeric_guards(s):
 for bad in [True,False,float('nan'),float('inf'),-float('inf'),'0']:
  denied(s,act(s,'pickup',drop_id='d',user_id='player',now=bad))
  denied(s,act(s,'expire',now=bad))
 dead=base();dead['combatants']['enemy']['hp']=0
 valid={'enemy_id':'enemy','drop_id':'d','roll':0,'chance':1,'owner_id':'player','now':0,'item':item()}
 for field in ['now','roll','chance']:
  invalid_values=[True,False,float('nan'),float('inf'),-float('inf'),'0']
  if field!='now':invalid_values += [-0.01,1.01]
  for bad in invalid_values:denied(dead,act(dead,'roll_drop',**{**valid,field:bad}))

def test_ru_004_loot_windows_expiry_and_capacity():
 s=drop();assert s['result']['dropped'] and available(s,'d')
 loot_numeric_guards(s)
 denied(s,act(s,'pickup',drop_id='d',user_id='other',now=59.999));denied(s,act(s,'pickup',drop_id='d',user_id='player',now=-1))
 owned=act(s,'pickup',drop_id='d',user_id='player',now=0);assert owned['result']['picked'] and pairs(owned)==[('fragment',1)] and not available(owned,'d');denied(owned,act(owned,'pickup',drop_id='d',user_id='player',now=1))
 shared=act(s,'pickup',drop_id='d',user_id='other',now=60);assert shared['result']['picked'] and pairs(shared,'other')==[('fragment',1)]
 denied(s,act(s,'pickup',drop_id='d',user_id='player',now=120));denied(s,act(s,'pickup',drop_id='d',user_id='absent',now=90))
 full=drop();full['inventories']['player']={'capacity':1,'slots':[{'item_id':'tool','quantity':1}]};denied(full,act(full,'pickup',drop_id='d',user_id='player',now=0));assert available(full,'d')
 later=drop(s,now=100,did='later');expired=act(later,'expire',now=120);assert not available(expired,'d') and available(expired,'later')
 for patch in [{'roll':.5,'chance':.5},{'roll':0,'chance':0}]:
  dead=base();dead['combatants']['enemy']['hp']=0;out=act(dead,'roll_drop',enemy_id='enemy',drop_id='d',owner_id='player',now=0,item=item(),**patch);assert out['result']['dropped'] is False and out['drops']=={}
 denied(s,act(s,'roll_drop',enemy_id='enemy',drop_id='d',roll=0,chance=1,owner_id='player',now=1,item=item()))
 alive=base();denied(alive,act(alive,'roll_drop',enemy_id='enemy',drop_id='new',roll=0,chance=1,owner_id='player',now=0,item=item()))
 initial=base();initial['combatants']['enemy']['hp']=0
 rows=browser(initial,[{'op':'click','selector':'#drop','response':'/action'},{'op':'click','selector':'#pickup','response':'/action'},{'op':'click','selector':'#pickup','response':'/action'}]);assert rows[1]['state']['result']['picked'] and pairs(rows[1]['state'])==[('fragment',1)] and 'fragment' in rows[1]['inventory'];assert rows[0]['canvas']!=rows[1]['canvas'];assert rows[2]['response_status']==400 and pairs(rows[2]['state'])==pairs(rows[1]['state'])

def test_ru_005_recipes_multiset_and_visible_fusion():
 s=base();s['recipes']={'z':{'level':1,'inputs':['ember','moss'],'result':'z','note':'kept'},'a':{'level':1,'inputs':['ember','ember'],'result':'a'},'later':{'level':2,'inputs':['ember','moss'],'result':'future'}}
 out=act(s,'encyclopedia');assert [r['recipe_id'] for r in out['result']['recipes']]==['a','z'];assert out['result']['recipes'][1]['note']=='kept'
 denied(s,act(s,'fuse',user_id='player',recipe_id='a'));denied(s,act(s,'fuse',user_id='absent',recipe_id='z'))
 twice=deepcopy(s);twice['creatures']['player']=['ember','moss','ember'];out=act(twice,'fuse',user_id='player',recipe_id='a');assert Counter(out['creatures']['player'])==Counter(['moss','a']);assert out['recipes']==s['recipes']
 later=act(s,'fuse',user_id='player',recipe_id='later');assert later['creatures']['player']==['future'];denied(later,act(later,'fuse',user_id='player',recipe_id='later'))
 rows=browser(base(),[{'op':'click','selector':'#encyclopedia','response':'/action'},{'op':'select','selector':'#recipe','value':'stone'},{'op':'click','selector':'#fuse','response':'/action'}]);assert any(o['value']=='stone' for o in rows[0]['options']);assert rows[-1]['state']['creatures']['player']==['stone'] and rows[-1]['creatures']=='stone'
