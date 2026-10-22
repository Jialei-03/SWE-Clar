"""Private behavior checks with independent integer/rational expectations."""
import csv
from io import StringIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
sys.path.insert(0,'/public_tests')
from lattice_support import Application, CandidateFailure, browser_session, request, read_download
from playwright.sync_api import expect, TimeoutError as BrowserTimeout


class Checks:
    def __init__(self):self.passed=[]
    def require(self,value,name):
        if not value:raise CandidateFailure(name)
        self.passed.append(name)


def problem(total=8,limit=32,policy='all',coordinates='raw'):
    return {'total':total,'limit':limit,'family_policy':policy,'coordinates':coordinates}


def raw_solutions(a,b,limit):
    out={}
    # Independent oracle enumerates coordinate pairs, not n-level remainders.
    for x in range(1,limit//a+1):
        for y in range(1,limit//b+1):
            n=a*x+b*y
            if a+b<n<=limit:out.setdefault(n,[]).append([x,y])
    return dict(sorted(out.items()))


def api(app,p,c):
    r=request(app,'/api/geometry',p);c.require(r['status']==200,'Valid problem receives HTTP 200');return r['body']


def expected_pairs(p):
    out=[]
    for b in range(1,p['total']):
        a=p['total']-b
        if a<=b:continue
        if p['family_policy']=='coprime' and math.gcd(a,b)!=1:continue
        if p['family_policy']=='opposite_parity' and (a-b)%2==0:continue
        out.append([a,b])
    return out


def close(a,b):
    return type(a) in (int,float) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)


def transformed(x,y,n,a,b,mode):
    if mode=='raw':return [x,y]
    if mode=='by_total':return [x/n,y/n]
    return [a*x/n,b*y/n]


def verify_geometry(value,p,c):
    c.require(all(value['problem'].get(k)==v for k,v in p.items()),'Response preserves the validated problem')
    c.require([[f['a'],f['b']] for f in value['families']]==expected_pairs(p),'Exact accepted coefficient families in b order')
    for family in value['families']:
        a,b=family['a'],family['b'];raw=raw_solutions(a,b,p['limit'])
        c.require([line['n'] for line in family['lines']]==list(raw),'Complete ordered equation levels')
        c.require(family['point_count']==sum(map(len,raw.values())),'Accurate per-family count')
        for line in family['lines']:
            expected=[transformed(x,y,line['n'],a,b,p['coordinates']) for x,y in raw[line['n']]]
            actual=line['points'];c.require(len(actual)==len(expected),'Complete point multiplicity')
            c.require(all(len(pair)==2 and all(close(v,w) for v,w in zip(pair,wanted)) for pair,wanted in zip(actual,expected)),'Correct transformed points in original x order')


def engine_calls(app,calls,c):
    identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    result=subprocess.run([sys.executable,'-I','/public_tests/engine_driver.py'],input=json.dumps(calls),capture_output=True,text=True,timeout=30,cwd=app.project,env={'PATH':os.environ['PATH'],'HOME':str(app.project),'SWECLAR_PROJECT_DIR':str(app.project),'PYTHONDONTWRITEBYTECODE':'1'},**identity)
    c.require(result.returncode==0,'Public Python API driver completes under candidate identity')
    try:value=json.loads(result.stdout)
    except ValueError:raise CandidateFailure('Public Python API produces invalid JSON transport')
    c.require(isinstance(value,list) and len(value)==len(calls),'Complete Python API call results')
    return value


def submit(page,p):
    page.locator('#total').fill(str(p['total']));page.locator('#limit').fill(str(p['limit']))
    page.locator('#family-policy').select_option(p['family_policy']);page.locator('#coordinates').select_option(p['coordinates'])
    with page.expect_response('**/api/geometry') as response:page.locator('#run').click()
    return response.value.json()


def count(value,keys=None):
    return sum(f['point_count'] for f in value['families'] if keys is None or f"{f['a']}:{f['b']}" in keys)


def gate_one(c):
    with Application() as app:
        c.require(request(app,'/health')['body'].get('ok') is True,'Health endpoint')
        p=problem();valid=api(app,p,c)
        for field,value in [('total',True),('total',8.0),('total',2),('total',41),('limit',8),('limit',601),('limit','32'),('family_policy','unknown'),('coordinates','unknown')]:
            r=request(app,'/api/geometry',{**p,field:value});c.require(r['status']==400 and r['body'].get('error')=='invalid_request','Invalid '+field+' rejected')
        for invalid in [None,[],{k:v for k,v in p.items() if k!='coordinates'},{**p,'extra':1}]:
            r=request(app,'/api/geometry',invalid,method='POST');c.require(r['status']==400,'Missing/extra/nonobject request rejected')
        c.require(request(app,'/api/geometry')['status']==404,'Wrong method rejected')
        verify_geometry(api(app,p,c),p,c)
        calls=[{'method':'solve','args':[3,True,12]},{'method':'transform','args':[True,2,9,5,2,'raw']},{'method':'pairs','args':[True,'all']},{'method':'solve','args':[4,4,20]},{'method':'solve','args':[6,2,8]},{'method':'transform','args':[1,2,9,5,2,'unknown']},{'method':'transform','args':[1,2,8,5,2,'raw']},{'method':'geometry','args':[{'total':8}]}]
        c.require(all(v=={'error':'ValueError'} for v in engine_calls(app,calls,c)),'Invalid direct arguments raise ValueError')
        with browser_session() as browser:
            page=browser.new_page(viewport={'width':390,'height':844});page.goto(app.url);expect(page.locator('#export')).to_be_disabled();blank=page.locator('#plot').screenshot()
            result=submit(page,p);expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(result)))
            expect(page.locator('[data-family-key]')).to_have_count(len(result['families']))
            c.require(page.locator('#plot').screenshot()!=blank,'Real form submission draws geometry')
            for w,h in [(390,844),(1280,900)]:page.set_viewport_size({'width':w,'height':h});c.require(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Responsive plot at '+str(w))
            fresh=browser.new_page();fresh.goto(app.url);expect(fresh.locator('#export')).to_be_disabled();expect(fresh.locator('[data-family-key]')).to_have_count(0);fresh.close();page.close()


def gate_two(c):
    with Application() as app:
        for p in [problem(3,4),problem(8,32),problem(17,93),problem(40,137)]:verify_geometry(api(app,p,c),p,c)
        calls=[{'method':'solve','args':args} for args in [(2,1,600),(23,17,233),(6,4,150),(3,1,6)]]
        for call,row in zip(calls,engine_calls(app,calls,c)):
            actual={int(n):points for n,points in row['value'].items()};c.require(actual==raw_solutions(*call['args']),'Independent exhaustive solver comparison including range and diagonal cases')


def gate_three(c):
    with Application() as app:
        cases=[problem(n, min(600,n+55),policy) for n in [4,9,16,25,40] for policy in ['coprime','opposite_parity']]
        for p in cases:verify_geometry(api(app,p,c),p,c)
        calls=[{'method':'pairs','args':[p['total'],p['family_policy']]} for p in cases]
        for p,row in zip(cases,engine_calls(app,calls,c)):c.require(row['value']==expected_pairs(p),'Public pair API honors selected policy')


def gate_four(c):
    with Application() as app:
        calls=[];expected=[]
        for a,b,x,y in [(5,2,3,2),(23,17,7,1),(7,3,1,1),(2,1,1,599-2)]:
            n=a*x+b*y
            for mode in ['raw','by_total','weighted']:
                calls.append({'method':'transform','args':[x,y,n,a,b,mode]});expected.append(transformed(x,y,n,a,b,mode))
        for row,wanted in zip(engine_calls(app,calls,c),expected):c.require(len(row['value'])==2 and all(close(a,b) for a,b in zip(row['value'],wanted)),'Direct normalization preserves rational value')
        for mode in ['by_total','weighted']:
            for p in [problem(9,47,'opposite_parity',mode),problem(16,71,'all',mode)]:verify_geometry(api(app,p,c),p,c)


def csv_matches(text,value,keys,c):
    rows=list(csv.reader(StringIO(text)));c.require(bool(rows) and rows[0]==['a','b','n','u','v'],'Documented CSV header')
    expected=[]
    for f in value['families']:
        if f"{f['a']}:{f['b']}" not in keys:continue
        for line in f['lines']:
            for u,v in line['points']:expected.append([f['a'],f['b'],line['n'],u,v])
    c.require(len(rows)-1==len(expected),'CSV preserves selected point multiplicity')
    c.require(all(len(row)==5 and all(close(float(a),b) for a,b in zip(row,wanted)) for row,wanted in zip(rows[1:],expected)),'CSV has actual selected coordinates in required order')


def check_projection(projected,value,keys,c):
    wanted=[]
    for f in value['families']:
        key=f"{f['a']}:{f['b']}"
        if key in keys:
            wanted.extend((key,line['n'],u,v) for line in f['lines'] for u,v in line['points'])
    x_max=max([1]+[p[2] for p in wanted]);y_max=max([1]+[p[3] for p in wanted]);bounds=projected['bounds']
    c.require(all(close(bounds[k],v) for k,v in {'x_min':0,'x_max':x_max,'y_min':0,'y_max':y_max}.items()),'One shared zero-based extent for selected families')
    actual=sorted(projected['points'],key=lambda p:(p['family_key'],p['n'],p['u'],p['v']));wanted.sort()
    c.require(len(actual)==len(wanted),'Projection includes each selected solution once')
    for point,(key,n,u,v) in zip(actual,wanted):
        c.require(point['family_key']==key and point['n']==n and all(close(point[k],w) for k,w in {'u':u,'v':v,'px':48+624*u/x_max,'py':432-384*v/y_max}.items()),'Projection preserves values and shared pixel scale')


def plot_pixels(page):
    return page.locator('#plot').evaluate('async(c)=>{await new Promise(requestAnimationFrame);return Array.from(c.getContext("2d").getImageData(0,0,720,480).data)}')


def expected_centers(value,keys):
    points=[(f"{f['a']}:{f['b']}",u,v) for f in value['families'] if f"{f['a']}:{f['b']}" in keys for line in f['lines'] for u,v in line['points']]
    xmax=max([1]+[u for _,u,_ in points]);ymax=max([1]+[v for _,_,v in points])
    return [(key,48+624*u/xmax,432-384*v/ymax) for key,u,v in points]


def patch_ink(blank,picture,x,y,radius=8):
    return {(xx-round(x),yy-round(y),tuple(picture[4*(yy*720+xx):4*(yy*720+xx)+3]))
            for yy in range(max(0,round(y)-radius),min(480,round(y)+radius+1))
            for xx in range(max(0,round(x)-radius),min(720,round(x)+radius+1))
            if max(abs(blank[4*(yy*720+xx)+i]-picture[4*(yy*720+xx)+i]) for i in range(4))>12}


def drawn_points(c,blank,picture,centers):
    for key,x,y in centers:
        c.require(bool(patch_ink(blank,picture,x,y)),f'Actual {key} point ink near independent projection {x:.2f},{y:.2f}')


def gate_five(c):
    with Application() as app,browser_session() as browser:
        page=browser.new_page(accept_downloads=True);page.goto(app.url);value=submit(page,problem(9,28,'all','by_total'));keys=[f"{f['a']}:{f['b']}" for f in value['families']]
        expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(value)))
        raw_value=api(app,problem(9,28),c)
        raw_projected=page.evaluate("async ([value,keys])=>(await import('/app.js')).project(value,keys)",[raw_value,keys])
        check_projection(raw_projected,raw_value,keys,c)
        with page.expect_download() as downloaded:page.locator('#export').click()
        c.require(downloaded.value.suggested_filename=='lattice.csv','Actual browser CSV download')
        csv_matches(read_download(downloaded.value).decode("utf-8-sig"),value,keys,c)
        calls=[];page.on('request',lambda req:calls.append(req.url) if '/api/geometry' in req.url else None)
        for key in keys:page.locator('[data-family-key="'+key+'"]').uncheck()
        expect(page.locator('#result-summary')).to_have_attribute('data-point-count','0');blank=page.locator('#plot').screenshot()
        empty_pixels=plot_pixels(page)
        for key in keys:page.locator('[data-family-key="'+key+'"]').check()
        all_pixels=plot_pixels(page);centers=expected_centers(value,keys)
        drawn_points(c,empty_pixels,all_pixels,centers)
        # Compare isolated point appearances, accepting color OR shape differences.
        appearances=[]
        for key in keys:
            isolated=[(x,y) for k,x,y in centers if k==key and all(k2==key or math.hypot(x-x2,y-y2)>18 for k2,x2,y2 in centers)]
            if isolated:
                x,y=isolated[0];appearances.append(patch_ink(empty_pixels,all_pixels,x,y))
        c.require(len(appearances)>=2 and any(a!=appearances[0] for a in appearances[1:]),'Multiple families have distinguishable actual point appearances')
        for key in keys:page.locator('[data-family-key="'+key+'"]').uncheck()
        chosen=keys[-1];page.locator('[data-family-key="'+chosen+'"]').check();expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(value,[chosen])))
        c.require(not calls,'Selection does not reissue geometry computation')
        c.require(page.locator('#plot').screenshot()!=blank,'Selected data changes actual canvas rendering')
        selected_pixels=plot_pixels(page);selected_centers=expected_centers(value,[chosen])
        drawn_points(c,empty_pixels,selected_pixels,selected_centers)
        removed=[(x,y) for key,x,y in centers if key!=chosen and all(math.hypot(x-a,y-b)>18 for _,a,b in selected_centers)]
        c.require(bool(removed),'Fixture distinguishes deselected families')
        c.require(all(not patch_ink(empty_pixels,selected_pixels,x,y,3) for x,y in removed),'Deselected family ink disappears at its separate positions')
        projected=page.evaluate("async ([value,keys])=>(await import('/app.js')).project(value,keys)",[value,[chosen,chosen,'missing']]);check_projection(projected,value,[chosen],c)
        empty=page.evaluate("async (value)=>(await import('/app.js')).project(value,[])",value);check_projection(empty,value,[],c)
        # Actual download remains based on accepted data after unsubmitted form edits.
        page.locator('#total').fill('11')
        with page.expect_download() as downloaded:page.locator('#export').click()
        csv_matches(read_download(downloaded.value).decode("utf-8-sig"),value,[chosen],c)
        page.locator('[data-family-key="'+chosen+'"]').uncheck()
        with page.expect_download() as downloaded:page.locator('#export').click()
        csv_matches(read_download(downloaded.value).decode("utf-8-sig"),value,[],c)
        result=submit(page,problem(8,29,'opposite_parity'));expect(page.locator('#result-summary')).to_have_attribute('data-point-count','0')
        with page.expect_download() as downloaded:page.locator('#export').click()
        csv_matches(read_download(downloaded.value).decode("utf-8-sig"),result,[],c);page.close()


def gate_six(c):
    with Application() as app,browser_session() as browser:
        page=browser.new_page();page.goto(app.url)
        # Use the published real HTTP controller, without depending on private state.
        page.evaluate("async()=>{const {ExplorerClient}=await import('/app.js');window.probe=new ExplorerClient();}")
        baseline=problem(8,24);page.evaluate('(p)=>probe.run(p)',baseline);old=page.evaluate('probe.result');key=f"{old['families'][-1]['a']}:{old['families'][-1]['b']}"
        page.evaluate('(key)=>probe.select([key])',key);csv_before=page.evaluate('probe.exportCSV()')
        page.evaluate('(p)=>probe.run(p)',{**baseline,'total':True})
        c.require(page.evaluate('probe.result')==old and page.evaluate('Array.from(probe.selectedKeys)')==[key] and page.evaluate('probe.exportCSV()')==csv_before and page.evaluate('Boolean(probe.error)'),'Current failure preserves previous accepted result, selection and export')
        held=[]
        def hold(route):held.append((route,route.fetch()))
        page.route('**/api/geometry',hold)
        first=problem(9,31);second=problem(10,35)
        page.evaluate('(p)=>{window.first=probe.run(p);}',first);page.wait_for_timeout(50)
        page.evaluate('(p)=>{window.second=probe.run(p);}',second);page.wait_for_timeout(50)
        c.require(len(held)==2,'A newer Run may be issued while another request is pending')
        held[1][0].fulfill(response=held[1][1]);page.evaluate('()=>second')
        newer=page.evaluate('probe.result');c.require(all(newer['problem'].get(k)==v for k,v in second.items()) and not page.evaluate('probe.error'),'Latest request replaces data and clears prior error')
        key=f"{newer['families'][-1]['a']}:{newer['families'][-1]['b']}";page.evaluate('(key)=>probe.select([key])',key)
        held[0][0].fulfill(response=held[0][1]);page.evaluate('()=>first')
        c.require(page.evaluate('probe.result')==newer and page.evaluate('Array.from(probe.selectedKeys)')==[key] and not page.evaluate('probe.error'),'Late older success cannot replace data or reset new selection')
        held.clear();page.evaluate('(p)=>{window.third=probe.run(p);}',first);page.wait_for_timeout(50);page.evaluate('(p)=>{window.fourth=probe.run(p);}',second);page.wait_for_timeout(50)
        held[1][0].fulfill(response=held[1][1]);page.evaluate('()=>fourth');held[0][0].abort();page.evaluate('()=>third')
        c.require(not page.evaluate('probe.error') and all(page.evaluate('probe.result.problem').get(k)==v for k,v in second.items()),'Late older failure cannot overwrite newer success')
        held.clear();before=page.evaluate('probe.result');page.evaluate('(p)=>{window.last=probe.run(p);}',first);page.wait_for_timeout(50);page.evaluate('()=>probe.dispose()');held[0][0].fulfill(response=held[0][1]);page.evaluate('()=>last')
        c.require(page.evaluate('probe.result')==before,'Disposed controller ignores in-flight completion')
        page.close()

    with Application() as app,browser_session() as browser:
        page=browser.new_page();page.goto(app.url);held=[]
        page.route('**/api/geometry',lambda route:held.append((route,route.fetch())))
        for p in [problem(9,31),problem(10,35)]:
            page.locator('#total').fill(str(p['total']));page.locator('#limit').fill(str(p['limit']))
            page.locator('#run').click();page.wait_for_timeout(50)
        c.require(len(held)==2,'Real Run button allows a newer pending intent')
        newest=held[1][1].json();held[1][0].fulfill(response=held[1][1])
        expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(newest)))
        held[0][0].fulfill(response=held[0][1]);page.wait_for_timeout(150)
        expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(newest)))
        c.require(set(page.locator('[data-family-key]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.familyKey)'))=={f"{f['a']}:{f['b']}" for f in newest['families']},'Real browser retains latest coefficient families after older response')
        page.unroute('**/api/geometry');page.locator('#total').fill('2');page.locator('#run').click();expect(page.locator('#error')).to_be_visible()
        expect(page.locator('#result-summary')).to_have_attribute('data-point-count',str(count(newest)))
        expect(page.locator('#export')).to_be_enabled();page.close()


GATES=[gate_one,gate_two,gate_three,gate_four,gate_five,gate_six]

def main():
    results=[];errors=[]
    for i,gate in enumerate(GATES,1):
        c=Checks();row={'ru_id':f'RU-{i:03d}','passed':False}
        try:gate(c);row.update(passed=True,detail='All executable checks passed')
        except (AssertionError,KeyError,TypeError,IndexError,ValueError,StopIteration,BrowserTimeout) as exc:row['detail']=type(exc).__name__+': '+str(exc)
        except Exception as exc:row['detail']='Unattributed evaluator/environment error: '+repr(exc);errors.append({'ru_id':row['ru_id'],'traceback':traceback.format_exc()})
        row['checks_passed']=c.passed;results.append(row)
    print(json.dumps({'harness_ok':not errors,'results':results,'infrastructure_errors':errors}));return 0 if not errors else 2

if __name__=='__main__':raise SystemExit(main())
