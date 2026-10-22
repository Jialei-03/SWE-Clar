import copy
import math
import re
from battle import begin,step,distance


class Rejected(ValueError):pass
def require(value,code='invalid_command'):
    if not value:raise Rejected(code)
def identifier(value):
    require(isinstance(value,str) and re.fullmatch('[A-Za-z0-9_-]{1,40}',value));return value
def number(value,low,high):
    require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high)
    return value


def template(value):
    require(isinstance(value,dict));result={'id':identifier(value.get('id'))}
    name=value.get('name');require(isinstance(name,str) and 1<=len(name.strip())<=60);result['name']=name.strip()
    require(value.get('kind') in ('melee','ranged'));result['kind']=value['kind']
    for key,low,high in [('health',1,1000),('attack',1,100),('defense',0,100),('speed',0.1,5),('range',0.8,8),('projectile_speed',0.1,20)]:
        result[key]=number(value.get(key),low,high)
    require(type(value.get('cooldown')) is int and 1<=value['cooldown']<=100);result['cooldown']=value['cooldown']
    return result


def initial():
    return {'config':{'templates':[
        {'id':'GUARD','name':'Guard','kind':'melee','health':40,'attack':8,'defense':2,'speed':2,'range':0.9,'cooldown':5,'projectile_speed':8},
        {'id':'SCOUT','name':'Scout','kind':'ranged','health':28,'attack':6,'defense':1,'speed':2.5,'range':3,'cooldown':8,'projectile_speed':7}],
        'placements':[{'id':'A1','template_id':'GUARD','team':'A','x':-4,'z':-2},
                      {'id':'A2','template_id':'SCOUT','team':'A','x':-4,'z':2},
                      {'id':'B1','template_id':'GUARD','team':'B','x':4,'z':-2},
                      {'id':'B2','template_id':'SCOUT','team':'B','x':4,'z':2}],
        'max_ticks':300},'battle':None}


def apply(data,command):
    require(isinstance(command,dict));data=copy.deepcopy(data);config=data['config'];kind=command.get('type')
    if kind=='reset':data['battle']=None;return data
    if kind=='start':
        require(data['battle'] is None,'reset_required')
        require({x['team'] for x in config['placements']}=={'A','B'},'both_teams_required')
        data['battle']=begin(config);return data
    if kind=='step':
        require(data['battle'] is not None and data['battle']['status']=='running','not_running')
        count=command.get('ticks',1);require(type(count) is int and 1<=count<=50)
        data['battle']=step(data['battle'],count);return data
    require(data['battle'] is None,'editing_locked')
    if kind=='template':
        value=template(command.get('value'));old=next((i for i,x in enumerate(config['templates']) if x['id']==value['id']),None)
        if old is None:
            require(len(config['templates'])<32,'catalog_full');config['templates'].append(value)
        else:config['templates'][old]=value
    elif kind=='delete_template':
        key=command.get('id');require(any(x['id']==key for x in config['templates']),'missing_template')
        require(not any(x['template_id']==key for x in config['placements']),'template_in_use')
        config['templates']=[x for x in config['templates'] if x['id']!=key]
    elif kind=='place':
        key=identifier(command.get('id'));source=command.get('template_id')
        require(any(x['id']==source for x in config['templates']),'missing_template')
        require(command.get('team') in ('A','B'));x=number(command.get('x'),-7.6,7.6);z=number(command.get('z'),-5.6,5.6)
        placement={'id':key,'template_id':source,'team':command['team'],'x':x,'z':z}
        others=[u for u in config['placements'] if u['id']!=key]
        require(all(distance(placement,u)>=0.8-1e-9 for u in others),'occupied')
        require(len(others)<32,'arena_full');config['placements']=others+[placement]
    elif kind=='remove':
        key=command.get('id');require(any(x['id']==key for x in config['placements']),'missing_unit')
        config['placements']=[x for x in config['placements'] if x['id']!=key]
    elif kind=='clear':config['placements']=[]
    elif kind=='limit':
        value=command.get('value');require(type(value) is int and 1<=value<=1000);config['max_ticks']=value
    else:raise Rejected('invalid_command')
    return data
