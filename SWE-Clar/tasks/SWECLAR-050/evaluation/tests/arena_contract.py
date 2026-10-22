import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import concurrent.futures
import math
import re
from collections import Counter
import os
import json
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');sys.path.insert(0,'/public_tests')
from harness import App
from preflight import preflight
from test_public import workshop,catalog,command,unit_template,pixels,open_page,FLAGS
from playwright.sync_api import sync_playwright,Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def setup(app,templates,placements,limit=300):
    command(app,'reset');command(app,'clear')
    for value in templates:command(app,'template',value=value)
    for id,template_id,team,x,z in placements:command(app,'place',id=id,template_id=template_id,team=team,x=x,z=z)
    return command(app,'limit',value=limit)['config']
def units(battle):return {x['id']:x for x in battle['units']}
def near(a,b):assert abs(a-b)<1e-8,(a,b)

def result_values(text,name,hp,damage):
    assert name in text
    values=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',text.replace(name,''))]
    # Field order and numeric formatting are presentation choices.
    assert not (Counter([hp,damage])-Counter(values)),(text,values)


def movement_and_melee():
    with App(PROJECT) as app,sync_playwright() as p:
        config=setup(app,[unit_template('FAST',speed=2,range=.8),unit_template('SLOW',speed=1,range=.8)],
                     [('A','FAST','A',-4,0),('B','SLOW','B',4,0)])
        command(app,'start');battle=command(app,'step',ticks=1)['battle'];u=units(battle)
        near(u['A']['x'],-3.8);near(u['B']['x'],3.9);assert battle['events']==[]
        battle=command(app,'step',ticks=9)['battle'];u=units(battle);near(u['A']['x'],-2);near(u['B']['x'],3)
        assert app.request('/api/state')['config']==config
        browser=_isolated_browser_launch(p.chromium, headless=True, args=FLAGS)
        try:
            page=open_page(browser,app);color=pixels(page,[{'x':-2,'y':.6,'z':0},{'x':-4,'y':.6,'z':0}])
            assert color[0][2]>color[0][0]+70 and not color[1][2]>color[1][0]+70,color
        finally:browser.close()
        setup(app,[unit_template('STRONG',health=100,attack=7,defense=2,range=8,cooldown=3),
                   unit_template('WEAK',health=5,attack=1,defense=1,range=8,cooldown=3),
                   unit_template('TOUGH',health=100,attack=1,defense=2,range=8,cooldown=3)],
              [('A','STRONG','A',0,0),('B1','WEAK','B',-2,0),('B2','TOUGH','B',2,0)])
        command(app,'start');battle=command(app,'step',ticks=4)['battle'];u=units(battle)
        hits=[x for x in battle['events'] if x['attacker']=='A'];assert [(x['tick'],x['target'],x['damage']) for x in hits]==[(1,'B1',5),(4,'B2',5)]
        assert u['A']['damage_dealt']==10 and u['B1']['hp']==0 and u['A']['hp']==98
        assert u['A']['next_attack']==7
        # Nearest target and ID tie order must beat a lower-health distant target.
        setup(app,[unit_template('T',health=100,attack=1,defense=0,range=8,cooldown=10),unit_template('LOW',health=1,attack=1,defense=0,range=8,cooldown=10)],
              [('A','T','A',0,0),('B1','T','B',2,0),('B2','LOW','B',-2,0)])
        command(app,'start');battle=command(app,'step',ticks=1)['battle'];assert battle['events'][0]['target']=='B1'
        # The client policy rounds only the comparison key to nine decimal
        # places. These legal, well-separated placements differ at the ninth
        # decimal; rounding to eight would incorrectly fall back to ID order.
        setup(app,[unit_template('TIGHT',health=100,attack=1,defense=0,range=8,cooldown=100)],
              [('A','TIGHT','A',0,0),('B1','TIGHT','B',1.0000000046,0),
               ('B2','TIGHT','B',-1.0000000044,0)])
        command(app,'start');battle=command(app,'step',ticks=1)['battle']
        assert battle['events'][0]['target']=='B2'
        setup(app,[unit_template('RUN',speed=5,range=.8,health=1000),unit_template('WALL',speed=.1,range=8,health=1000,attack=1,defense=100)],
              [('A1','RUN','A',-2,0),('A2','WALL','A',-1.2,0),('B','WALL','B',2,0)])
        command(app,'start');battle=command(app,'step',ticks=5)['battle'];u=units(battle);near(u['A1']['x'],-2)
        assert math.hypot(u['A1']['x']-u['A2']['x'],u['A1']['z']-u['A2']['z'])>=.8-1e-9


def projectiles():
    with App(PROJECT) as app,sync_playwright() as p:
        setup(app,[unit_template('SLOW_SHOT',kind='ranged',health=1,attack=50,defense=0,range=8,cooldown=1,projectile_speed=1),
                   unit_template('FAST_SHOT',kind='ranged',health=20,attack=2,defense=0,range=8,cooldown=100,projectile_speed=20)],
              [('A','SLOW_SHOT','A',-1,0),('B','FAST_SHOT','B',1,0)])
        command(app,'start');one=command(app,'step',ticks=1)['battle']
        assert [x['type'] for x in one['events']]==['launch','launch'] and [x['id'] for x in one['projectiles']]==[1,2]
        assert units(one)['A']['hp']==1 and units(one)['B']['hp']==20
        assert [(x['x'],x['z']) for x in one['projectiles']]==[(-1,0),(1,0)]
        two=command(app,'step',ticks=1)['battle'];assert units(two)['A']['hp']==0 and units(two)['B']['hp']==20
        assert two['status']=='running' and len(two['projectiles'])==1
        near(two['projectiles'][0]['x'],-.9)
        six=command(app,'step',ticks=4)['battle'];assert len(six['projectiles'])==1;near(six['projectiles'][0]['x'],-.5)
        browser=_isolated_browser_launch(p.chromium, headless=True, args=FLAGS)
        try:
            page=open_page(browser,app)
            points=[{'x':-.5,'y':.8,'z':0},{'x':0,'y':.8,'z':0}]
            before=pixels(page,points)
            moved=command(app,'step',ticks=5)['battle'];near(moved['projectiles'][0]['x'],0)
            page.reload();page.wait_for_function('window.arenaView?.data?.battle?.tick===11')
            after=pixels(page,points)
            assert before[0]!=after[0] and before[1]!=after[1],(before,after)
        finally:browser.close()
        final=command(app,'step',ticks=50)['battle'];assert final['status']=='finished' and final['tick']==21 and final['winner']=='draw' and final['reason']=='elimination'
        assert units(final)['A']['damage_dealt']==20 and units(final)['B']['damage_dealt']==1 and len(final['units'])==2
        assert [(e['tick'],e['attacker'],e['damage']) for e in final['events'] if e['type']=='hit']==[(2,'B',1),(21,'A',20)]
        # Home on the target's current position, not its position at launch.
        setup(app,[unit_template('STILL',health=1000,attack=1,defense=0,range=8,cooldown=100),
                   unit_template('SHOT',kind='ranged',health=1000,attack=1,defense=0,range=8,cooldown=100,projectile_speed=2),
                   unit_template('MOVE',health=1000,attack=1,defense=0,range=.8,speed=1,cooldown=100)],
              [('A0','STILL','A',2,-2),('A1','SHOT','A',-3,0),('B','MOVE','B',2,2)])
        command(app,'start');battle=command(app,'step',ticks=2)['battle'];shot=battle['projectiles'][0];d=math.hypot(5,1.9)
        near(shot['x'],-3+.2*5/d);near(shot['z'],.2*1.9/d)
        # Simultaneous arriving shots resolve in creation order; no extra hit on a dead target.
        setup(app,[unit_template('R',kind='ranged',health=10,attack=1,defense=0,range=8,cooldown=100,projectile_speed=20),
                   unit_template('LOW',health=1,attack=1,defense=0,range=8,cooldown=100)],
              [('A1','R','A',-2,-1),('A2','R','A',-2,1),('B','LOW','B',2,0)])
        command(app,'start');battle=command(app,'step',ticks=10)['battle'];hits=[e for e in battle['events'] if e.get('target')=='B' and e['type']=='hit']
        assert len(hits)==1 and hits[0]['attacker']=='A1' and units(battle)['A2']['damage_dealt']==0


def results_and_replay():
    with App(PROJECT) as app,sync_playwright() as p:
        config=setup(app,[unit_template('WIN',name='Winner sample',health=30,attack=20,defense=3,range=8,cooldown=3),
                          unit_template('LOSE',name='Defeated sample',health=7,attack=2,defense=1,range=8,cooldown=3)],
                     [('A','WIN','A',-1,0),('B','LOSE','B',1,0)])
        command(app,'start');final=command(app,'step',ticks=50)['battle']
        assert final['winner']=='A' and final['tick']==1 and final['reason']=='elimination' and len(final['units'])==2
        assert units(final)['A']['damage_dealt']==7 and units(final)['B']['hp']==0
        browser=_isolated_browser_launch(p.chromium, headless=True, args=FLAGS)
        try:
            page=open_page(browser,app);assert page.locator('#results').is_visible()
            assert re.search(r'\bA\b',page.locator('#outcome').inner_text()) and page.locator('[data-result-unit]').count()==2
            result_values(page.locator('[data-result-unit="A"]').inner_text(),'Winner sample',30,7)
            result_values(page.locator('[data-result-unit="B"]').inner_text(),'Defeated sample',0,0)
            assert page.locator('[data-unit]').count()==2
            points=[{'x':1+dx,'y':.15,'z':dz} for dx in [-.2,0,.2] for dz in [-.2,0,.2]]
            dead=pixels(page,points)
            canvas_height=page.locator('#arena').bounding_box()['height']
            command(app,'reset');command(app,'clear');page.reload()
            page.wait_for_function('window.arenaView?.data?.config.placements.length===0')
            # Removing results can grow the arena; compare the same projection
            # scale so grid antialiasing cannot masquerade as retained geometry.
            empty_height=page.locator('#arena').bounding_box()['height']
            page.set_viewport_size({'width':1280,'height':round(900+canvas_height-empty_height)})
            page.wait_for_function('(height)=>Math.abs(document.querySelector("#arena").getBoundingClientRect().height-height)<1',arg=canvas_height)
            empty=pixels(page,points)
            assert sum(a!=b for a,b in zip(dead,empty))>=3,'Defeated geometry is not visible'
            for placement in config['placements']:command(app,'place',**placement)
            command(app,'start');assert command(app,'step',ticks=50)['battle']==final
        finally:browser.close()
        for _ in range(3):
            reset=command(app,'reset');assert reset=={'config':config,'battle':None}
            command(app,'start');assert command(app,'step',ticks=50)['battle']==final
        before=app.request('/api/state')
        for event in [{'type':'start'},{'type':'step','ticks':1},{'type':'clear'},{'type':'remove','id':'A'},{'type':'template','value':unit_template('X')}]:
            app.request('/api/command',event,status=400);assert app.request('/api/state')==before
        setup(app,[unit_template('DRAW',kind='ranged',health=1000,attack=1,defense=100,range=8,cooldown=100,projectile_speed=.1)],
              [('A','DRAW','A',-2,0),('B','DRAW','B',2,0)],limit=3)
        command(app,'start');battle=command(app,'step',ticks=50)['battle'];assert battle['winner']=='draw' and battle['tick']==3 and battle['reason']=='tick_limit'
        setup(app,[unit_template('MOVING',health=1000,speed=1,range=.8)], [('A','MOVING','A',-4,0),('B','MOVING','B',4,0)])
        command(app,'start');command(app,'step',ticks=4);before=app.request('/api/state');app.stop();app.start();assert app.request('/api/state')==before
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda n:command(app,'step',ticks=n),[5,7]))
        assert app.request('/api/state')['battle']['tick']==16
        before=app.request('/api/state')
        for count in [True,0,-1,51,1.5]:
            app.request('/api/command',{'type':'step','ticks':count},status=400);assert app.request('/api/state')==before
        command(app,'reset');command(app,'clear');command(app,'place',id='ALONE',template_id='MOVING',team='A',x=0,z=0)
        before=app.request('/api/state');app.request('/api/command',{'type':'start'},status=400);assert app.request('/api/state')==before


def main():
    try:prepared=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([workshop,catalog,movement_and_melee,projectiles,results_and_replay],1):
        try:test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':prepared,'results':results}));return 0


if __name__=='__main__':raise SystemExit(main())
