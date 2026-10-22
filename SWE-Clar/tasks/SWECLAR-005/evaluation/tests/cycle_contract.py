"""Independent UTC/calendar and real browser-notification checks."""
import sys as _browser_sys
_browser_sys.path.insert(0, '/public_tests')
from browser_isolation import launch as _isolated_browser_launch
import contextlib,copy,datetime,json,sys,time,traceback
sys.path.insert(0,'/public_tests')
from cycle_support import Site,open_page,create,notifications,CandidateFailure
from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
DAY=datetime.timedelta(days=1)
PHASES=['menstrual','follicular','ovulatory','luteal']
NOW=datetime.datetime(2028,2,29,7,59,59,tzinfo=datetime.timezone.utc)


@contextlib.contextmanager
def session(zone='UTC',granted=True,now=NOW):
    with Site() as site,sync_playwright() as p:
        browser=_isolated_browser_launch(p.chromium, channel='chromium', headless=True)
        try:
            context=browser.new_context(permissions=['notifications'] if granted else [],timezone_id=zone)
            context.grant_permissions(['notifications'] if granted else [],origin=site.url)
            page=context.new_page();page.clock.install(time=now);page.clock.pause_at(now);open_page(page,site)
            yield page,context,site
        finally:browser.close()


def inputs(**changes):
    return {'periodStart':'2028-02-20','cycleLength':28,'periodLength':5,'asOf':'2028-02-29',**changes}


def batch(page,cases):
    rows=page.evaluate('''async(cases)=>{let mod;try{mod=await import('/src/cycle-planner.js')}catch(e){return {moduleError:String(e)}};return cases.map(input=>{const before=JSON.stringify(input);try{const result=mod.buildCyclePlan(input);return {result,immutable:JSON.stringify(input)===before}}catch(e){return {error:e.message,immutable:JSON.stringify(input)===before}}});}''',cases)
    assert isinstance(rows,list),rows
    assert len(rows)==len(cases) and all(r['immutable'] for r in rows)
    return rows


def oracle(value):
    anchor=datetime.date.fromisoformat(value['periodStart']);today=datetime.date.fromisoformat(value['asOf']);length=value['cycleLength'];period=value['periodLength']
    # Locate the containing interval with calendar arithmetic, independently of JS date math.
    while anchor>today:anchor-=length*DAY
    while anchor+length*DAY<=today:anchor+=length*DAY
    remaining=length-period-2;follicular=remaining//2;timeline=[]
    for index in range(length):
        phase=PHASES[0] if index<period else PHASES[1] if index<period+follicular else PHASES[2] if index<period+follicular+2 else PHASES[3]
        timeline.append({'day':index+1,'date':(anchor+index*DAY).isoformat(),'phase':phase})
    current=(today-anchor).days+1;phase=timeline[current-1]['phase'];pool=(value.get('promptPools') or {}).get(phase,[])
    selected=pool[(value.get('seed',0)+(today-datetime.date(1970,1,1)).days)%len(pool)] if pool else None
    return {'currentDay':current,'currentPhase':phase,'cycleStart':anchor.isoformat(),'timeline':timeline,'recommendation':selected}


def storage(page):return page.evaluate("JSON.parse(localStorage.getItem('cycle-journals'))")
def configure(page,**overrides):
    values={'periodStart':'2028-02-20','cycleLength':28,'periodLength':5,'seed':0,
        'promptPools':{p:['Reminder '+p] for p in PHASES},'reminderTime':'08:00','remindersEnabled':False,**overrides}
    for field,element in [('periodStart','period-start'),('cycleLength','cycle-length'),('periodLength','period-length'),('seed','seed'),('reminderTime','reminder-time')]:page.locator('#'+element).fill(str(values[field]))
    page.locator('#prompt-pools').fill(json.dumps(values['promptPools']));page.locator('#reminders-enabled').set_checked(values['remindersEnabled']);page.locator('#settings-form button').click();expect(page.locator('#feedback')).to_have_text('saved');return values


def tick(page,milliseconds=1000):
    page.clock.run_for(milliseconds)
    # Actual browser notification work is asynchronous outside the controlled page clock.
    page.evaluate('()=>Promise.resolve()')


def await_notifications(page,count):
    deadline=time.monotonic()+5;actual=[]
    while time.monotonic()<deadline:
        actual=notifications(page)
        if len(actual)==count:return actual
        time.sleep(.04)
    raise AssertionError(f'Expected {count} actual browser notifications, got {actual}')


def close_notifications(page):
    page.evaluate('async()=>{const r=await navigator.serviceWorker.ready;(await r.getNotifications()).forEach(n=>n.close());}')
    await_notifications(page,0)


def check_1():
    with session() as (page,context,site):
        valid=[inputs(),inputs(cycleLength=8,periodLength=2),inputs(cycleLength=60,periodLength=54),inputs(promptPools=None),inputs(promptPools={}),inputs(seed=-2147483648)]
        rows=batch(page,valid);assert all('result' in r for r in rows)
        assert batch(page,valid)==rows
        invalid=[None,[],{},inputs(periodStart='2027-02-29'),inputs(periodStart='2028-2-01'),inputs(asOf='2028-04-31'),inputs(asOf='2100-01-01'),inputs(asOf='1999-12-31'),inputs(asOf='2028-02-29T00:00:00Z'),inputs(cycleLength=True),inputs(cycleLength=7),inputs(cycleLength=61),inputs(cycleLength=28.5),inputs(periodLength=0),inputs(periodLength=23),inputs(seed=2147483648),inputs(seed=-2147483649),inputs(seed=1.5),inputs(promptPools=[]),inputs(promptPools={'unknown':[]}),inputs(promptPools={'menstrual':'message'}),inputs(promptPools={'menstrual':[' ']}),inputs(promptPools={'menstrual':[1]}),inputs(promptPools={'menstrual':['x'*201]}),inputs(promptPools={'menstrual':['x']*33}),inputs(extra=True)]
        assert all(r.get('error')=='invalid_input' for r in batch(page,invalid))
        first=create(page,'  First journal  ');second=create(page,'Second journal');assert first and second and first!=second
        state=storage(page);assert state['activeId']==second and len(state['profiles'])==2 and state['profiles'][0]['label']=='First journal'
        for profile in state['profiles']:
            settings=profile['settings'];assert settings['periodStart']=='2028-02-29' and settings['cycleLength']==28 and settings['periodLength']==5 and settings['seed']==0 and settings['reminderTime']=='08:00' and settings['remindersEnabled'] is False
        expect(page.locator('#label')).to_have_value('')


def check_2():
    cases=[]
    for start in ['2000-01-01','2028-02-25','2027-12-27','2028-03-09','2099-12-29']:
        for length,period in [(8,1),(9,3),(28,5),(29,4),(60,54)]:
            anchor=datetime.date.fromisoformat(start)
            for delta in [-length-1,-length,-1,0,period-1,period,length-1,length,length+1,2*length+3]:
                date=anchor+delta*DAY
                if 2000<=date.year<=2099:cases.append(inputs(periodStart=start,cycleLength=length,periodLength=period,asOf=date.isoformat()))
    for zone in ['UTC','America/New_York','Asia/Kolkata']:
        with session(zone=zone) as (page,_,__):
            for value,row in zip(cases,batch(page,cases)):
                expected=oracle(value);result=row.get('result');assert isinstance(result,dict),(zone,value,row)
                assert type(result.get('currentDay')) is int
                for key in ['currentDay','currentPhase','cycleStart','recommendation']:assert result.get(key)==expected[key],(zone,value,key,result,expected)
                timeline=result.get('timeline');assert isinstance(timeline,list) and len(timeline)==len(expected['timeline'])
                for actual,wanted in zip(timeline,expected['timeline']):
                    assert isinstance(actual,dict) and type(actual.get('day')) is int
                    assert all(actual.get(k)==v for k,v in wanted.items()),(actual,wanted)


def check_3():
    pools={p:[f'{p} entry {n}' for n in range(4)] for p in PHASES};cases=[]
    for day in range(1,29):
        for seed in [-2147483648,-7,0,1,2147483647]:
            cases.append(inputs(periodStart='2028-02-01',asOf=(datetime.date(2028,2,1)+(day-1)*DAY).isoformat(),promptPools=pools,seed=seed))
    cases += [inputs(promptPools=p) for p in [None,{}, {'menstrual':['Wrong phase']},{'follicular':[]},{'follicular':['  Literal <b>text</b> & symbols  ']}]]
    with session() as (page,_,__):
        rows=batch(page,cases)
        for value,row in zip(cases,rows):assert row.get('result',{}).get('recommendation')==oracle(value)['recommendation'],(value,row)
        assert rows==batch(page,cases)


def check_4():
    with session(zone='America/Los_Angeles') as (page,_,__):
        label='<img src=x onerror="window.labelRan=1">';ident=create(page,label);expect(page.locator('#profile-select option')).to_have_text(label);expect(page.locator('#journal-title')).to_have_text(label);assert page.evaluate('window.labelRan') is None
        literal='<img src=x onerror="window.promptRan=1"> & literal';pools={phase:[literal] for phase in PHASES}
        settings=configure(page,promptPools=pools);expect(page.locator('#recommendation')).to_have_text(literal);assert page.evaluate('window.promptRan') is None
        for width in [375,1280]:
            page.set_viewport_size({'width':width,'height':1800});tick(page,50);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');expect(page.locator('#prompt-pools')).to_be_visible();expect(page.locator('#settings-form button')).to_be_visible()
        before=storage(page);rendered=page.locator('#timeline').inner_text();recommendation=page.locator('#recommendation').inner_text()
        for element,value in [('cycle-length','7'),('period-length','0'),('seed','1.5'),('prompt-pools','{')]:
            configure(page,**settings);page.locator('#'+element).fill(value);page.locator('#settings-form button').click();expect(page.locator('#feedback')).to_have_text('invalid_input');expect(page.locator('#'+element)).to_have_value(value)
            assert storage(page)==before and page.locator('#timeline').inner_text()==rendered and page.locator('#recommendation').inner_text()==recommendation
        configure(page,periodStart='2028-03-04',cycleLength=29,periodLength=4,promptPools=pools)
        wanted=oracle(inputs(periodStart='2028-03-04',cycleLength=29,periodLength=4,promptPools=pools))
        expect(page.locator('#current-day')).to_have_text(str(wanted['currentDay']));expect(page.locator('#cycle-start')).to_have_text(wanted['cycleStart'])
        dates=page.locator('#timeline [data-date]').evaluate_all('(xs)=>xs.map(x=>x.dataset.date)');assert dates==[d['date'] for d in wanted['timeline']]
        expect(page.locator('#timeline [aria-current=date]')).to_have_attribute('data-date','2028-02-29')
        saved=storage(page);page.reload();page.wait_for_function('navigator.serviceWorker.controller!==null');assert storage(page)==saved;expect(page.locator('#period-start')).to_have_value('2028-03-04')
        second=create(page,'Other');expect(page.locator('#current-day')).to_have_text('1');page.locator('#profile-select').select_option(ident);expect(page.locator('#period-start')).to_have_value('2028-03-04')
        # Jump to the next UTC date; timers run once and the actual page must refresh.
        page.clock.fast_forward(16*60*60*1000+2000);expect(page.locator('#today')).to_have_text('2028-03-01');expect(page.locator('#timeline [aria-current=date]')).to_have_attribute('data-date','2028-03-01')
        malformed=['{','null','[]',json.dumps({'activeId':None,'profiles':'bad'}),json.dumps({'activeId':'missing','profiles':[]}),json.dumps({'activeId':'x','profiles':[{'id':'x','label':'Bad','settings':{},'notifiedDays':[]}]})]
        for raw in malformed:
            page.evaluate("raw=>localStorage.setItem('cycle-journals',raw)",raw);page.reload();page.wait_for_function('navigator.serviceWorker.controller!==null');expect(page.locator('#workspace')).to_be_hidden();assert page.locator('#profile-select option').count()==0
            create(page,'Repaired');assert len(storage(page)['profiles'])==1


def assert_notice(item,ident,date,phase,body):
    assert all(item.get(k)==v for k,v in {'title':'Cycle Calendar reminder','body':body,'tag':f'cycle:{ident}:{date}'}.items())
    assert isinstance(item.get('data'),dict)
    assert all(item['data'].get(k)==v for k,v in {'profileId':ident,'date':date,'phase':phase}.items())


def check_5():
    with session(zone='America/Los_Angeles') as (page,context,site):
        a=create(page,'A');configure(page,remindersEnabled=True);tick(page,500);assert notifications(page)==[] and storage(page)['profiles'][0]['notifiedDays']==[]
        tick(page,500);items=await_notifications(page,1);assert_notice(items[0],a,'2028-02-29','follicular','Reminder follicular');expect(page.locator('#reminder-history')).to_contain_text('2028-02-29')
        close_notifications(page);tick(page,2000);assert notifications(page)==[]
        configure(page,periodStart='2028-02-28',reminderTime='00:00',remindersEnabled=True);tick(page,1000);assert notifications(page)==[]
        page.reload();page.wait_for_function('navigator.serviceWorker.controller!==null');tick(page,1000);assert notifications(page)==[]
        b=create(page,'B');configure(page,remindersEnabled=True);tick(page);items=await_notifications(page,1);assert_notice(items[0],b,'2028-02-29','follicular','Reminder follicular')
        close_notifications(page);page.locator('#profile-select').select_option(a);tick(page);assert notifications(page)==[]
        # Midnight eligibility is UTC, and the prior journal's history must not suppress it.
        current=page.evaluate('Date.now()');next_midnight=int(datetime.datetime(2028,3,1,tzinfo=datetime.timezone.utc).timestamp()*1000)
        page.clock.fast_forward(next_midnight-current+1000);items=await_notifications(page,1);assert_notice(items[0],a,'2028-03-01','menstrual','Reminder menstrual')
        close_notifications(page)
        # Skipped dates never produce a backlog.
        page.clock.fast_forward(2*86400000);items=await_notifications(page,1);assert items[0]['data']['date']=='2028-03-03';assert storage(page)['profiles'][0]['notifiedDays']==['2028-02-29','2028-03-01','2028-03-03']
        close_notifications(page);configure(page,remindersEnabled=False,reminderTime='00:00');page.clock.fast_forward(86400000);assert notifications(page)==[]
    late=datetime.datetime(2028,2,29,10,tzinfo=datetime.timezone.utc)
    with session(granted=False,now=late) as (page,context,site):
        ident=create(page);configure(page,remindersEnabled=True);assert page.evaluate('Notification.permission')=='denied';tick(page,2000);assert notifications(page)==[] and storage(page)['profiles'][0]['notifiedDays']==[]
        context.grant_permissions(['notifications'],origin=site.url);tick(page);item=await_notifications(page,1)[0];assert_notice(item,ident,'2028-02-29','follicular','Reminder follicular')
    with session(now=late) as (page,_,__):
        ident=create(page);configure(page,promptPools={},remindersEnabled=True);tick(page,2000);assert notifications(page)==[] and storage(page)['profiles'][0]['notifiedDays']==[]
        configure(page,remindersEnabled=True);tick(page);assert_notice(await_notifications(page,1)[0],ident,'2028-02-29','follicular','Reminder follicular')
    with session(now=late) as (page,_,__):
        ident=create(page)
        page.evaluate('''()=>{const original=ServiceWorkerRegistration.prototype.showNotification;window.notificationAttempts=0;window.failNotification=true;ServiceWorkerRegistration.prototype.showNotification=function(...args){window.notificationAttempts++;if(window.failNotification)return Promise.reject(new Error('Injected service failure'));return original.apply(this,args)}}''')
        configure(page,remindersEnabled=True);tick(page,1000);assert page.evaluate('window.notificationAttempts')>=1;assert storage(page)['profiles'][0]['notifiedDays']==[] and notifications(page)==[]
        page.evaluate('window.failNotification=false')
        tick(page,1000);assert_notice(await_notifications(page,1)[0],ident,'2028-02-29','follicular','Reminder follicular')


def main():
    results=[];errors=[]
    for n,fn in enumerate([check_1,check_2,check_3,check_4,check_5],1):
        try:fn();row={'ru_id':f'RU-{n:03d}','passed':True}
        except (AssertionError,BrowserTimeout) as e:
            traceback.print_exc(file=sys.stderr);row={'ru_id':f'RU-{n:03d}','passed':False,'detail':str(e)[-2000:]}
        except Exception as e:
            traceback.print_exc(file=sys.stderr);errors.append(f'RU-{n:03d}: {type(e).__name__}: {e}');row={'ru_id':f'RU-{n:03d}','passed':False,'detail':'Unattributed evaluator error'}
        results.append(row)
    print(json.dumps({'harness_ok':not errors,'results':results,'infrastructure_errors':errors}));return 2 if errors else 0


if __name__=='__main__':raise SystemExit(main())
