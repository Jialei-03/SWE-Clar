"""Deterministic fixed-tick combat, separate from editing and rendering."""
import copy
import math

DT = 0.1
RADIUS = 0.4


def distance(a,b):return math.hypot(a['x']-b['x'],a['z']-b['z'])


def begin(config):
    templates={x['id']:x for x in config['templates']}
    units=[]
    for placement in sorted(config['placements'],key=lambda x:x['id']):
        unit=copy.deepcopy(templates[placement['template_id']]);unit.update(placement)
        unit.update(hp=unit['health'],next_attack=1,damage_dealt=0)
        units.append(unit)
    return {'status':'running','tick':0,'winner':None,'reason':None,'units':units,
            'projectiles':[],'events':[],'max_ticks':config['max_ticks'],'next_projectile':1}


def damage(state,attacker,target,amount,kind):
    amount=min(target['hp'],max(1,amount))
    target['hp']-=amount;attacker['damage_dealt']+=amount
    state['events'].append({'tick':state['tick'],'type':'hit','kind':kind,'attacker':attacker['id'],
                            'target':target['id'],'damage':amount,'remaining_hp':target['hp']})


def finish(state):
    # The provisional stopping condition only handles a time limit.
    if state['tick']>=state['max_ticks']:
        state['status']='finished';state['winner']='draw';state['reason']='tick_limit'


def advance_projectiles(state):
    units={x['id']:x for x in state['units']};pending=[]
    for shot in state['projectiles']:
        target=units[shot['target']]
        if target['hp']<=0:continue
        remaining=distance(shot,target);travel=shot['speed']*DT
        if remaining<=travel+1e-9:
            damage(state,units[shot['attacker']],target,shot['attack'],'ranged')
        else:
            shot['x']+=(target['x']-shot['x'])*travel/remaining
            shot['z']+=(target['z']-shot['z'])*travel/remaining
            pending.append(shot)
    state['projectiles']=pending


def turn(state,unit):
    # Movement and attack decisions await implementation after clarification.
    return


def step(battle,ticks):
    state=copy.deepcopy(battle)
    for _ in range(ticks):
        if state['status']!='running':break
        state['tick']+=1
        advance_projectiles(state)
        for unit in state['units']:
            if unit['hp']>0:turn(state,unit)
        finish(state)
    return state
