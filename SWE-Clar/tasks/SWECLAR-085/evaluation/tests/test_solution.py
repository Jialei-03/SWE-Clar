"""Private assertions over browser APIs, rendered DOM and real HTTP/media activity."""
import json,sys,time
from urllib.parse import urljoin
sys.path.insert(0,'/public_tests')
from support import application,play

def ru001(page):
    # Observe server time outside the page so oracle traffic cannot count as
    # application fetches. A wrap can occur; retry a pair after that wrap.
    for attempt in range(2):
        first=live_sample(page);page.wait_for_timeout(1300);second=live_sample(page)
        if second[0]>=first[0]:break
    assert_live_advances(first,second)
    calls=[];offset=12.0
    def live(route):
        calls.append(offset);route.fulfill(json={'offset':offset})
    page.route('**/api/live',live)
    play(page)
    assert calls,'First play must fetch live offset'
    assert abs(page.locator('audio').evaluate('(a)=>a.currentTime')-offset)<1,'First play must follow current linear programme'
    before=page.locator('audio').evaluate('(a)=>a.currentTime')
    page.wait_for_timeout(300)
    assert page.locator('audio').evaluate('(a)=>a.currentTime')>before+.15,'Media must advance'
    page.locator('#pause').click();offset=38.0;count=len(calls)
    page.locator('#resume').click()
    page.wait_for_function("!document.querySelector('audio').paused && !document.querySelector('audio').seeking")
    assert len(calls)>count,'Resume must issue its own live request'
    assert abs(page.locator('audio').evaluate('(a)=>a.currentTime')-offset)<1,'Resume must follow current linear programme'
    play(page,'recent');assert page.locator('audio').evaluate('(a)=>a.currentTime')<1.5
    assert page.locator('audio').evaluate('(a)=>a.readyState>=2')

def live_sample(page):
    start=time.monotonic();response=page.request.get(urljoin(page.url,'/api/live'));assert response.ok
    value=response.json()['offset'];end=time.monotonic()
    return value,start,end

def assert_live_advances(first,second):
    delta=second[0]-first[0]
    assert second[1]-first[2]-.1 <= delta <= second[2]-first[1]+.1,'Live endpoint must advance with independently measured elapsed time'

def ru002(page):
    play(page);assert page.locator('#schedule .playing').count()==1
    title=page.locator('#selected').inner_text();page.locator('#pause').click()
    pos=page.locator('audio').evaluate('(a)=>a.currentTime');page.wait_for_timeout(300)
    assert page.locator('audio').evaluate('(a)=>a.paused') and abs(page.locator('audio').evaluate('(a)=>a.currentTime')-pos)<.08
    assert page.locator('.playing').count()==0,'Paused selection must not appear playing'
    assert page.locator('#selected').inner_text()==title
    play(page,'recent');assert page.locator('#recent .playing').count()==1 and page.locator('#schedule .playing').count()==0

def ru003(page):
    cases=[('schedule','Dawn sample','Sample artist A','Synthetic set A'),('recent','Night sample','Sample artist B','Synthetic set B')]
    def handler(row):
        def respond(route):route.fulfill(json=[row])
        return respond
    for section,title,artist,album in cases:
        row={'id':section+'-custom','title':title,'artist':artist,'album':album,'url':'/tone.wav','live':section=='schedule'}
        page.route('**/api/'+section,handler(row))
    page.reload();page.wait_for_selector('[data-id="schedule-custom"]');page.wait_for_selector('[data-id="recent-custom"]')
    for section,title,artist,album in cases:
        play(page,section)
        info=page.evaluate('({title:navigator.mediaSession.metadata?.title,artist:navigator.mediaSession.metadata?.artist,album:navigator.mediaSession.metadata?.album,state:navigator.mediaSession.playbackState})')
        assert info=={'title':title,'artist':artist,'album':album,'state':'playing'},'Current full metadata must replace previous selection'
        page.locator('#pause').click();assert page.evaluate('navigator.mediaSession.playbackState')=='paused'

def ru004(page):
    play(page);page.locator('#seconds').fill('1.4');page.locator('#set-timer').click();page.wait_for_timeout(550)
    page.locator('#show-timer').click();assert 0<float(page.locator('#remaining').inner_text())<1.1
    page.wait_for_timeout(1000);assert page.locator('audio').evaluate('(a)=>a.paused'),'Timer must pause real audio'
    play(page);page.locator('#seconds').fill('.4');page.locator('#set-timer').click();page.locator('#cancel-timer').click();page.wait_for_timeout(650)
    assert not page.locator('audio').evaluate('(a)=>a.paused'),'Cancelled timer must not pause'

def ru005(page):
    before=page.locator('#recent').inner_text();hits=[]
    def replacement(route):
        hits.append(route.request.url)
        route.fulfill(json=[{'id':'new-one','title':'Changed schedule','artist':'Group','album':'Collection','url':'/tone.wav','live':True}])
    page.route('**/api/schedule',replacement);page.locator('#refresh-schedule').click();page.wait_for_selector('[data-id="new-one"]')
    assert len(hits)==1 and page.locator('#schedule').inner_text()=='Changed schedule'
    assert page.locator('#recent').inner_text()==before
    page.route('**/api/recent',lambda route:route.fulfill(json=[]));page.locator('#refresh-recent').click();page.wait_for_function("document.querySelector('#recent').children.length===0")
    assert page.locator('#schedule').inner_text()=='Changed schedule'

results=[]
for i,check in enumerate([ru001,ru002,ru003,ru004,ru005],1):
    try:
        with application() as page:check(page)
        passed=True;detail='Actual browser behavior passed'
    except Exception as error:passed=False;detail=type(error).__name__+': '+str(error)
    results.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
print(json.dumps({'harness_ok':True,'results':results}))
