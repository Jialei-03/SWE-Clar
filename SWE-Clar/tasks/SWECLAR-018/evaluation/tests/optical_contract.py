"""Protected tests observe image-derived HTTP results and rendered browser pixels."""
import contextlib
import copy
import io
import json
import math
import os
import sys
from pathlib import Path
sys.path.insert(0,'/opt/sweclar')
sys.path.insert(0,'/public_tests')
from harness import App, CandidateFailure
from preflight import preflight
from test_public import run as public_run
from playwright.sync_api import Error as BrowserError
PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


def pgm(points=None, width=32, height=24, dark=30, background=220):
    if points is None: points={(x,y) for x in range(10,14) for y in range(8,12)}
    pixels=[dark if (x,y) in points else background for y in range(height) for x in range(width)]
    return f'P2\n# independently generated evaluator raster\n{width} {height}\n255\n'+' '.join(map(str,pixels))


def capture():
    return {'capabilities':{'fps':20,'width':32,'height':24},
            'config':{'phase_ms':1000,'threshold':60,'min_area':4,'max_area':80,'max_gap_ms':300,
                      'max_motion_px':3,'max_lighting_delta':20,'max_area_change':0.2,'max_gaze_px':3},
            'frames':[{'t_ms':t,'pgm':pgm(),'target':[11.5,9.5]} for t in range(0,2000,250)]}


def result(app, document): return app.request('/api/analyze',document)
def near(actual, expected): assert type(actual) in (int,float) and abs(actual-expected)<=1e-6,(actual,expected)
def verdict(report, expected, reason): assert (report['verdict'],report['reason'])==(expected,reason),report


def ru1():
    with contextlib.redirect_stdout(io.StringIO()): public_run()
    with App(PROJECT) as app:
        assert app.request('/api/preview',{'pgm':'P2\t2 # width\n1\n255\n0\t255\n'})=={'width':2,'height':1,'pixels':[0,255]}
        for text in ['P2 0 1 255','P2 129 1 255 0','P2 1 1 256 0','P2 1 1 255 2.0','P2 1 1 255','P2 1 1 255 +2']:
            app.request('/api/preview',{'pgm':text},status=400)
        good=capture(); before=result(app,good)
        mutations=[]
        for path,value in [('fps',True),('width',0),('height',129),('fps',241)]:
            d=copy.deepcopy(good);d['capabilities'][path]=value;mutations.append(d)
        for path,value in [('threshold',256),('phase_ms',99),('max_gap_ms',0),('min_area',81),('max_motion_px',-1),('max_gaze_px',True),('max_area_change',float('nan'))]:
            d=copy.deepcopy(good);d['config'][path]=value;mutations.append(d)
        for edit in [lambda d:d['frames'][1].update(t_ms=0),lambda d:d['frames'][-1].update(t_ms=2000),
                     lambda d:d['frames'][0].update(target=[-1,0]),lambda d:d['frames'][0].update(target=[32,0]),
                     lambda d:d['frames'][0].update(pgm=pgm(width=31)),lambda d:d.update(frames=[]),
                     lambda d:d['frames'][0].update(t_ms=0.5),lambda d:d['config'].pop('max_gap_ms')]:
            d=copy.deepcopy(good);edit(d);mutations.append(d)
        for d in mutations:
            app.request('/api/analyze',d,status=400)
            assert app.request('/api/report')==before
        for d in [[],{},None]:
            # None is sent as JSON null rather than a GET.
            app.request('/api/analyze',json.dumps(d),status=400)
        app.request('/api/preview',{'pgm':None},status=400)


def ru2():
    with App(PROJECT) as app:
        for changes in [{'fps':9},{'width':15},{'height':15}]:
            d=capture();d['capabilities'].update(changes)
            for f in d['frames']: f.update(pgm='not a PGM',target=[0,0])
            assert result(app,d)=={'verdict':'not_measurable','reason':'capability','measurements':[]}
        d=capture();d['capabilities']={'fps':10,'width':16,'height':16}
        for f in d['frames']: f.update(pgm=pgm({(x,y) for x in range(6,10) for y in range(6,10)},width=16,height=16),target=[7.5,7.5])
        assert len(result(app,d)['measurements'])==8


def ru3():
    with App(PROJECT) as app:
        d=capture();r=result(app,d)
        assert [x['phase'] for x in r['measurements']]==['light']*4+['gaze']*4
        assert [x['t_ms'] for x in r['measurements']]==[f['t_ms'] for f in d['frames']]
        shapes=[{(x,y) for x in range(3,6) for y in range(7,10)},
                {(5,5),(6,5),(7,5),(5,6),(5,7),(6,7)}]
        for points in shapes:
            d=capture();d['config']['threshold']=47
            d['frames'][0].update(pgm=pgm(points|{(20,18),(21,18)},dark=47),target=[1,2])
            row=result(app,d)['measurements'][0]
            assert row['area']==len(points)
            x=sum(x for x,y in points)/len(points);y=sum(y for x,y in points)/len(points)
            near(row['cx'],x);near(row['cy'],y);near(row['gaze_error'],math.hypot(x-1,y-2))
        for config in [{'min_area':16,'max_area':16},{'threshold':30}]:
            d=capture();d['config'].update(config);assert result(app,d)['measurements'][0]['area']==16
        tied={(x,y) for x in range(4,6) for y in range(4,6)}|{(x,y) for x in range(6,8) for y in range(6,8)}
        invalid=[(set(),{}),(tied,{}),({(0,y) for y in range(4,8)},{}),
                 ({(x,23) for x in range(8,12)},{}),(None,{'min_area':17}),(None,{'max_area':15}),(None,{'threshold':29})]
        for points,config in invalid:
            d=capture();d['config'].update(config);d['frames'][0]['pgm']=pgm(points)
            row=result(app,d)['measurements'][0]
            assert all(row[k] is None for k in ['area','cx','cy','gaze_error']),row
        d=capture();d['config']['phase_ms']=800
        d['frames']=[{'t_ms':t,'pgm':pgm(),'target':[11.5,9.5]} for t in [0,400,799,800,1200,1599]]
        assert [x['phase'] for x in result(app,d)['measurements']]==['light']*3+['gaze']*3


def ru4():
    with App(PROJECT) as app:
        base=capture()
        # Equality at quality limits is acceptable.
        d=copy.deepcopy(base);d['config'].update(max_gap_ms=250,max_motion_px=0,max_lighting_delta=0)
        verdict(result(app,d),'stable','within_limits')
        variants=[]
        d=copy.deepcopy(base);d['frames'][0]['pgm']=pgm(set());variants.append(d)
        d=copy.deepcopy(base);d['frames']=d['frames'][2:];variants.append(d)
        d=copy.deepcopy(base);d['frames']=d['frames'][:-1];variants.append(d)
        d=copy.deepcopy(base);d['frames'].pop(2);variants.append(d)
        for keep in [[0,4,5,6,7],[0,1,2,3,4]]:
            d=copy.deepcopy(base);d['frames']=[d['frames'][i] for i in keep];d['config']['max_gap_ms']=2000;variants.append(d)
        d=copy.deepcopy(base);d['frames'][2]['pgm']=pgm({(x+4,y) for x in range(10,14) for y in range(8,12)});variants.append(d)
        d=copy.deepcopy(base);d['frames'][2]['pgm']=pgm(background=190);variants.append(d)
        for d in variants:
            # A deliberate target error cannot override quality rejection.
            for f in d['frames']: f['target']=[0,0]
            r=result(app,d);verdict(r,'not_measurable','quality');assert len(r['measurements'])==len(d['frames'])
        # Exact brightness difference of 16: 16 dark pixels in a 16x16 image, background delta 16*16/15.
        # Integer fixture instead uses 768 pixels, 48 dark -> background delta 16 gives mean delta 15.
        d=copy.deepcopy(base);points={(x,y) for x in range(8,16) for y in range(8,14)}
        for i,f in enumerate(d['frames']): f['pgm']=pgm(points,background=200 if i%2 else 216);f['target']=[11.5,10.5]
        d['config']['max_lighting_delta']=15
        verdict(result(app,d),'stable','within_limits')
        d['config']['max_lighting_delta']=14.99;verdict(result(app,d),'not_measurable','quality')
        d=copy.deepcopy(base)
        for i,f in enumerate(d['frames']): f['pgm']=pgm({(x+(3 if i%2 else 0),y) for x in range(10,14) for y in range(8,12)});f['target']=[13,9.5]
        verdict(result(app,d),'stable','within_limits')
        d['config']['max_motion_px']=2.99;verdict(result(app,d),'not_measurable','quality')


def ru5():
    with App(PROJECT) as app:
        d=capture();verdict(result(app,d),'stable','within_limits')
        # Area 16 -> 20 means 0.25, compared strictly; same centroid displacement remains under quality limit.
        d['frames'][1]['pgm']=pgm({(x,y) for x in range(10,15) for y in range(8,12)})
        d['config']['max_area_change']=0.25
        verdict(result(app,d),'stable','within_limits')
        d['config']['max_area_change']=0.2499;verdict(result(app,d),'deviation','threshold')
        d=capture()
        for f in d['frames'][4:]: f['target']=[14.5,13.5]  # 3-4-5 distance
        d['config']['max_gaze_px']=5;verdict(result(app,d),'stable','within_limits')
        d['config']['max_gaze_px']=4.999;verdict(result(app,d),'deviation','threshold')
        d=capture()
        for f in d['frames'][:4]: f['target']=[0,0]
        d['frames'][5]['pgm']=pgm({(x,y) for x in range(9,15) for y in range(7,13)})
        verdict(result(app,d),'stable','within_limits')
        # Deterministic repeat uses actual new images, not a memorized fixture/report.
        first=result(app,d);assert result(app,copy.deepcopy(d))==first
        d['frames'][4]['target']=[0,0];verdict(result(app,d),'deviation','threshold')


def main():
    try: health=preflight()
    except Exception as error:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(error)],'results':[]}));return 2
    results=[]
    for i,test in enumerate([ru1,ru2,ru3,ru4,ru5],1):
        try:
            test();results.append({'ru_id':f'RU-{i:03d}','passed':True})
        except (AssertionError,BrowserError,KeyError,TypeError,ValueError) as error:
            results.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'harness_ok':True,'preflight':health,'results':results}));return 0


if __name__=='__main__': raise SystemExit(main())
