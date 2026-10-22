"""Independent hand-derived lifecycle examples and boundary checks, grouped by RU."""
import json,os,subprocess,sys
from pathlib import Path
from candidate_proxy import run,call

def bar(h,l,c=None):
    c=(h+l)/2 if c is None else c
    return dict(open=c,high=h,low=l,close=c)

def rows(value,key='active_levels'):
    return [(r['side'],r['price'],r['created_at'],r['status'],r['extends_to']) for r in value[key]]

def prices(value,key='active_levels'):
    return [(r['side'],r['price'],r['created_at']) for r in value[key]]

def events(value):
    return [(r['side'],r['price'],r['index']) for r in value['break_events']]

def test_ru_001_contract_validation_console():
    sample=[bar(10,0),bar(9,1),bar(8,2)]
    a=run(sample,2);assert a==run(sample,2)
    assert all(isinstance(a[k],list) for k in ('active_levels','display_levels','break_events'))
    for bars,lookback,opts in [(None,1,{}),({},1,{}),([None],1,{}),([{}],1,{}),([bar(1,2)],1,{}),([bar(2,0,3)],1,{}),([dict(open=True,high=2,low=0,close=1)],1,{}),([dict(open=1,high=float('inf'),low=0,close=1)],1,{}),([dict(open=1,high=2,low=0,close=float('nan'))],1,{}),([],True,{}),([],1.5,{}),([],0,{}),([],1,{'tick_size':0}),([],1,{'tick_size':float('inf')}),([],1,{'tick_size':True}),([],1,{'min_distance_ticks':-1}),([],1,{'min_distance_ticks':1.5}),([],1,{'extend_points':True}),([],1,{'extend_points':-1}),([],1,{'keep_past_levels':1}),([],1,{'hide_broken_levels':None}),([],1,{'use_close_instead_of_wick':'yes'})]:
        assert call(bars,lookback,**opts).get('error')=='ValueError',(bars,lookback,opts)
    for short in [[],sample[:1],sample[:2]]:
        assert all(not run(short,2)[k] for k in ('active_levels','display_levels','break_events'))
    # Observe real file and stdin console output with independently calculated public-mode values.
    request=dict(bars=sample,lookback=2);root=Path(os.environ['CANDIDATE_ROOT'])
    kwargs={} if os.environ.get('LEVELS_HOST_HELPER') else {'user':1000,'group':1000,'extra_groups':[]}
    p=subprocess.run([sys.executable,str(root/'cli.py')],input=json.dumps(request),capture_output=True,text=True,cwd=root,timeout=8,**kwargs)
    assert p.returncode==0,p.stderr
    assert prices(json.loads(p.stdout))==[('high',10,2),('low',0,2)]

def test_ru_002_prior_window_both_sources():
    sample=[bar(12,0,3),bar(10,2,8),bar(99,-99,6)]
    assert prices(run(sample,2))==[('high',12,2),('low',0,2)]
    assert prices(run(sample,2,use_close_instead_of_wick=True))==[('high',8,2),('low',3,2)]
    descending=[bar(12,0,4),bar(10,2,6),bar(9,3,5),bar(8,4,6)]
    # Earlier creation survives and captures the earlier window, irrespective of later bars.
    assert prices(run(descending,2,keep_past_levels=True))==[('high',12,2),('low',0,2),('high',10,3),('low',2,3)]
    negative=[bar(-1,-9,-4),bar(-2,-8,-5)]
    assert prices(run(negative,1))==[('high',-1,1),('low',-9,1)]

def test_ru_003_current_replacement():
    sample=[bar(10,0),bar(9,1),bar(8,2),bar(7,3),bar(6,4)]
    result=run(sample,2,hide_broken_levels=False)
    assert prices(result)==[('high',8,4),('low',2,4)]
    assert rows(result,'display_levels')==rows(result)
    assert events(result)==[]
    # Suppression occurs before replacement: rejected candidates preserve current records.
    result=run(sample,2,min_distance_ticks=2,tick_size=1)
    assert prices(result)==[('high',10,2),('low',0,2)]
    # A broken record is distinct from a replaced record and may be displayed.
    result=run([bar(10,0),bar(9,1),bar(11,2)],1,hide_broken_levels=False)
    assert prices(result)==[('high',9,2),('low',1,2)]
    assert prices(result,'display_levels')==[('high',10,1),('high',9,2),('low',1,2)]

def test_ru_004_retained_lifetime():
    sample=[bar(20,-10),bar(18,-8),bar(16,-6),bar(14,-4),bar(12,-2),bar(10,0)]
    result=run(sample,1,keep_past_levels=True)
    assert prices(result)==[(side,p,i) for i,(h,l) in enumerate([(20,-10),(18,-8),(16,-6),(14,-4),(12,-2)],1) for side,p in [('high',h),('low',l)]]
    assert not events(result)
    # One side breaks without discarding unbroken opposite-side history.
    result=run(sample+[bar(21,1)],1,keep_past_levels=True)
    assert [(s,i) for s,p,i in prices(result)]==[('low',i) for i in range(1,6)]+[('high',6),('low',6)]
    assert events(result)==[('high',p,6) for p in [20,18,16,14,12]]

def test_ru_005_spacing_boundaries():
    sample=[bar(10,0),bar(9,1),bar(8,2),bar(7,3)]
    assert prices(run(sample,1,keep_past_levels=True,min_distance_ticks=1))==[('high',10,1),('low',0,1),('high',8,3),('low',2,3)]
    assert len(run([bar(10,0)]*4,1,keep_past_levels=True)['active_levels'])==6
    assert len(run([bar(10,0)]*4,1,keep_past_levels=True,min_distance_ticks=1)['active_levels'])==2
    assert len(run([bar(1,1)]*3,1,keep_past_levels=True,min_distance_ticks=1)['active_levels'])==2
    decimal_bars=[bar(.3,0),bar(.2,.1),bar(.15,.12)]
    assert len(run(decimal_bars,1,keep_past_levels=True,min_distance_ticks=1,tick_size=.1)['active_levels'])==2
    # All active levels participate, not only the most recent; broken levels do not suppress.
    sample=[bar(10,0),bar(9,1),bar(8,2),bar(11,3),bar(10.5,4)]
    result=run(sample,1,keep_past_levels=True,min_distance_ticks=1,hide_broken_levels=False)
    assert ('high',8,3) in prices(result,'display_levels') and ('high',11,4) in prices(result)

def test_ru_006_break_events_display_extension():
    sample=[bar(10,0),bar(9,1),bar(10,0),bar(11,-1),bar(12,-2)]
    result=run(sample,1,keep_past_levels=True,hide_broken_levels=False,extend_points=0)
    assert events(result)==[('high',10,3),('low',0,3),('high',9,3),('low',1,3),('high',10,4),('low',0,4)]
    assert all(r['extends_to']==r['created_at'] for r in result['display_levels'])
    hidden=run(sample,1,keep_past_levels=True,hide_broken_levels=True,extend_points=7)
    assert rows(hidden,'display_levels')==rows(hidden)
    assert all(r['extends_to']==r['created_at']+7 for r in hidden['active_levels'])
    assert events(hidden)==events(result)
    assert len([r for r in result['display_levels'] if r['status']=='broken'])==6
    # Even close-derived levels break on later wicks, not close; equality is not a break.
    equal=run([bar(10,0),bar(9,1),bar(10,0)],1,keep_past_levels=True)
    assert ('high',10,1) in prices(equal) and ('low',0,1) in prices(equal)
    close=run([bar(10,0,5),bar(8,2,5),bar(7,3,5)],1,use_close_instead_of_wick=True,keep_past_levels=True)
    assert events(close)==[('high',5,2),('low',5,2)]
