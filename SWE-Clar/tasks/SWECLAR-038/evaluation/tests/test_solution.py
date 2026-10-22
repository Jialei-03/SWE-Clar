"""Independent ordered-assignment oracle; never imports candidate code."""
from collections import Counter
from itertools import product
import json,math,random,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_proxy import call
SLOTS=({'QB'},{'RB'},{'WR'},{'WR','TE'},{'RB','WR','TE'})
def pool():
    return [dict(id=f'synthetic-{i}',position=p,projected_points=s) for i,(p,s) in enumerate(zip(['QB','RB','RB','WR','WR','TE','WR'],[20,15,10,18,12,14,1]))]
def oracle(players):
    rows=[]
    for assignment in product(*[[p for p in players if p['position'] in slot] for slot in SLOTS]):
        ids=[p['id'] for p in assignment]
        if len(set(ids))==5:rows.append(dict(player_ids=ids,score=sum(p['projected_points'] for p in assignment)))
    return sorted(rows,key=lambda r:(-r['score'],tuple(r['player_ids'])))
def same_rows(actual,expected):
    assert len(actual)==len(expected),'Incorrect output count'
    for a,b in zip(actual,expected):
        assert a['player_ids']==b['player_ids'],'Not the true ordered top-N assignments'
        assert type(a['score']) in (int,float) and math.isclose(a['score'],b['score'],rel_tol=1e-9,abs_tol=1e-9)
def ru001():
    a=call(pool(),2,'deep'); b=call(pool(),2,'deep')
    for k in ['lineups','considered','unused_player_ids']:assert a[k]==b[k]
    assert isinstance(a['lineups'],list) and type(a['considered']) is int and isinstance(a['unused_player_ids'],list)
def ru002():
    players=pool(); rows=call(players,50,'deep')['lineups']; assert rows
    positions={p['id']:p['position'] for p in players}
    for row in rows:
        ids=row['player_ids']; assert len(ids)==len(set(ids))==5
        assert all(positions[pid] in slot for pid,slot in zip(ids,SLOTS))
def ru003():
    for seed in [7,29,113]:
        players=pool(); rng=random.Random(seed)
        for p in players:p['projected_points']=rng.randint(-8,24)/4
        rng.shuffle(players); expected=oracle(players)
        for mode in ['deep','realtime']:same_rows(call(players,20,mode)['lineups'],expected[:20])
    players=pool()
    for p in players:p['projected_points']=0
    same_rows(call(players,1000,'deep')['lineups'],oracle(players))
    high=[dict(id=f'active-{i:03}',position=['QB','RB','WR','TE'][i%4],projected_points=10+(i*37%71)/4) for i in range(24)]
    expected=oracle(high)[:10000]; assert len(expected)==10000
    # Even the best row containing a reserve is below the entire selected optimum.
    assert -1000000+4*max(p['projected_points'] for p in high)<expected[-1]['score']
    low=[dict(id=f'reserve-{i:03}',position=['QB','RB','WR','TE'][i%4],projected_points=-1000000) for i in range(576)]
    players=high+low; random.Random(91).shuffle(players)
    same_rows(call(players,10000,'deep')['lineups'],expected)
def ru004():
    players=pool(); total=len(oracle(players))
    for mode in ['deep','realtime']:
        for limit in [1,3,total+4]:
            r=call(players,limit,mode); assert len(r['lineups'])==min(limit,total) and r['considered']==total
        r=call([p for p in players if p['position']!='QB'],5,mode); assert r['lineups']==[] and r['considered']==0
    for limit,mode in [(0,'deep'),(-1,'deep'),(True,'deep'),(1.5,'deep'),(1,'other')]:
        r=call(players,limit,mode); assert r['error']['code']=='invalid_request' and 'lineups' not in r
    assert call([{}],0,'deep')['error']['code']=='invalid_request'
    large=[dict(id=f'p-{i}',position=['QB','RB','WR','TE'][i%4],projected_points=i/4) for i in range(600)]; total=0
    for positions in product(*[sorted(s) for s in SLOTS]):
        available=Counter(p['position'] for p in large); ways=1
        for position in positions:ways*=available[position]; available[position]-=1
        total+=ways
    assert call(large,1,'deep')['considered']==total
def ru005():
    players=pool(); r=call(players+[dict(players[0])],1,'deep')
    assert r['error']['code']=='duplicate_player_id' and 'lineups' not in r
    for bad in [None,[{}],[dict(id='',position='QB',projected_points=1)],[dict(id='a',position='QB',projected_points=True)],[dict(id='a',position='OTHER',projected_points=1)],[dict(id='a',position='QB',projected_points='1')]]:
        r=call(bad,1,'deep'); assert isinstance(r['error']['code'],str) and r['error']['code'] and 'lineups' not in r
    for value in [float('nan'),float('inf'),float('-inf')]:
        bad=[dict(id='invalid-number',position='QB',projected_points=value)]
        r=call(bad,1,'deep'); assert r.get('error',{}).get('code') and 'lineups' not in r
    r=call(players+[dict(players[0]),{}],1,'deep')
    assert r.get('error',{}).get('code') not in [None,'','duplicate_player_id'] and 'lineups' not in r
    for sample in [[],players,[{**p,'metadata':{'synthetic':True}} for p in players]]:
        for limit in [1,1000]:
            r=call(sample,limit,'deep'); used={pid for row in r['lineups'] for pid in row['player_ids']}
            assert r['unused_player_ids']==sorted({p['id'] for p in sample}-used)
def main():
    if not Path('/public_tests/invoke.py').is_file():return {'harness_ok':False,'results':[],'error':'Missing benchmark invocation helper'}
    rows=[]
    for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
        try:test(); passed,detail=True,'passed'
        except subprocess.TimeoutExpired:return {'harness_ok':False,'results':[],'error':'Unattributed wall timeout; reproduce before scoring'}
        except Exception as error:passed,detail=False,type(error).__name__+': '+str(error)
        rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
