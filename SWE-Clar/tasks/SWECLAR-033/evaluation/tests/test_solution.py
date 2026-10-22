from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from xml.sax.saxutils import escape
import json
import unittest
import sys
from conftest import load_solution

def item(title='Paper & Light', start='2030-04-01', end='2030-05-07', url='/shows/paper'):
    return dict(title=title,start_date=start,end_date=end,url=url,image='/images/paper.svg')

def source(m, kind='JSON', url='https://museum.example.test/feeds/current', sid='gallery', city='Example City'):
    return m.process_exhibition_action({'sources':{},'exhibitions':{}},{'type':'add_source','source':dict(source_id=sid,museum='Example Gallery',city=city,url=url,feed_type=kind)})

def sync(m, state, body, **extra):
    observed=[]
    def fetch(url): observed.append(url); return body
    action=dict(type='sync',source_id='gallery',current_date='2030-05-01',**extra)
    before=deepcopy((state,action))
    out=m.process_exhibition_action(state,action,fetch_text=fetch)
    assert (state,action)==before
    assert observed==[state['sources']['gallery']['url']]
    return out

@contextmanager
def feed_server(body):
    observed=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append(self.path); self.send_response(200); self.end_headers(); self.wfile.write(body.encode())
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=Thread(target=server.serve_forever,daemon=True); worker.start()
    try: yield f'http://127.0.0.1:{server.server_port}/feeds/current', observed
    finally: server.shutdown(); server.server_close(); worker.join()

def test_ru_001_entry_and_real_http():
    m=load_solution()
    with feed_server(json.dumps([item()])) as (url,hits):
        state=source(m,url=url); before=deepcopy(state)
        action=dict(type='sync',source_id='gallery',current_date='2030-05-01',items=[item('UNTRUSTED PREPARSED INPUT')])
        saved=deepcopy(action)
        out=m.process_exhibition_action(state,action)
        assert state==before and action==saved
        assert hits==['/feeds/current']
        assert len(out['exhibitions'])==1
        assert next(iter(out['exhibitions'].values()))['title']=='Paper & Light'
        json.dumps(out,allow_nan=False)

def test_ru_002_record_values_and_atomic_errors():
    m=load_solution(); state=source(m)
    out=sync(m,state,json.dumps([item()]))
    assert out['sources']['gallery']['last_fetch']=='2030-05-01'
    assert type(out['result']['updated']) is int and out['result']['updated']==1
    timestamped=sync(m,state,json.dumps([item(),item('Second',url='/second')]),fetched_at='2030-05-01T17:42:00Z')
    assert timestamped['sources']['gallery']['last_fetch']=='2030-05-01T17:42:00Z'
    assert type(timestamped['result']['updated']) is int and timestamped['result']['updated']==2
    actual=next(iter(out['exhibitions'].values()));expected=dict(
        source_id='gallery',
        title='Paper & Light',museum='Example Gallery',city='Example City',
        start_date='2030-04-01',end_date='2030-05-07',url='https://museum.example.test/shows/paper',
        image='https://museum.example.test/images/paper.svg')
    assert all(actual.get(k)==v for k,v in expected.items())
    assert actual.get('status')=='closing_soon'
    boundaries=[item('Closed',end='2030-04-30',url='/closed'),item('Today',start='2030-05-01',end='2030-05-01',url='/today'),item('Seven',end='2030-05-08',url='/seven'),item('Eight',end='2030-05-09',url='/eight'),item('Future',start='2030-05-02',end='2030-05-07',url='/future')]
    stored=sync(m,state,json.dumps(boundaries))['exhibitions']
    assert {r['title']:r['status'] for r in stored.values()}==dict(Closed='closed',Today='closing_soon',Seven='closing_soon',Eight='ongoing',Future='upcoming')
    for broken in [item(start='bad'),item(start='2030-06-01'),dict(title='Missing fields')]:
        result=sync(m,out,json.dumps([item('Would change existing record'),broken]),fetched_at='2030-05-02')
        assert result['error']['code']=='invalid_exhibition'
        assert result['exhibitions']==out['exhibitions'] and result['sources']==out['sources']
    for body in ['{broken','{}']:
        result=sync(m,out,body,fetched_at='2030-05-02')
        assert result['error']['code']=='invalid_feed' and result['exhibitions']==out['exhibitions'] and result['sources']==out['sources']
    def failure(url): raise OSError('synthetic transport failure')
    result=m.process_exhibition_action(out,dict(type='sync',source_id='gallery',current_date='2030-05-01'),fetch_text=failure)
    assert result['error']['code']=='fetch_failed' and result['sources']==out['sources']

def test_ru_003_updates_replays_and_source_identity():
    m=load_solution(); state=source(m)
    one=sync(m,state,json.dumps([item('First'),item('Second',url='/shows/two')]))
    two=sync(m,one,json.dumps([item('Renamed',url=' https://museum.example.test/shows/paper ')]))
    assert len(two['exhibitions'])==2
    assert next(x for x in two['exhibitions'].values() if x['url']=='https://museum.example.test/shows/paper')['title']=='Renamed'
    repeated=sync(m,two,json.dumps([item('Renamed',url=' https://museum.example.test/shows/paper ')]))
    assert repeated==two
    unrelated=source(m,sid='other')['sources']['other']
    two['sources']['other']=unrelated
    result=m.process_exhibition_action(two,dict(type='sync',source_id='other',current_date='2030-05-01'),fetch_text=lambda url:json.dumps([item('Independent')]))
    assert len(result['exhibitions'])==3

def check_actual_wire_format(kind):
    m=load_solution(); state=source(m,kind=kind)
    bodies={
        'JSON':json.dumps([item()]),
        'RSS':'<rss version="2.0"><channel><title>Synthetic feed</title><item><title>Paper &amp; Light</title><link>/shows/paper</link><start_date>2030-04-01</start_date><end_date>2030-05-07</end_date><image>/images/paper.svg</image></item></channel></rss>',
        'ics':'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-event\r\nSUMMARY:Paper &amp; Light\r\nDTSTART;VALUE=DATE:20300401\r\nDTEND;VALUE=DATE:20300508\r\nURL:/shows/paper\r\nIMAGE:/images/paper.svg\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'.replace('Paper &amp; Light','Paper & Li\r\n ght'),
        'html':'<html><body><h2>Unrelated title</h2><article class="exhibition extra"><h2>Paper &amp; <em>Light</em></h2><a class="details" href="/shows/paper">Details</a><time data-field="start_date" datetime="2030-04-01"></time><time data-field="end_date" datetime="2030-05-07"></time><img src="/images/paper.svg"></article></body></html>'}
    out=sync(m,state,bodies[kind]); rows=list(out['exhibitions'].values())
    assert len(rows)==1 and out['result'].get('manual_entry_required',False) is False
    assert type(out['result']['updated']) is int and out['result']['updated']==1
    row=rows[0]
    assert row['title']=='Paper & Light' and row['start_date']=='2030-04-01' and row['end_date']=='2030-05-07'
    assert row['url']=='https://museum.example.test/shows/paper' and row['image'].endswith('/images/paper.svg')

def test_ru_004_unfold_escaping_and_manual():
    m=load_solution(); state=source(m,'ICS')
    text='BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Paper\\, Light\\nSecond line\nDTSTART;VALUE=DATE:20300501\nDTEND;VALUE=DATE:20300502\nURL:/one\nEND:VEVENT\nEND:VCALENDAR'
    row=next(iter(sync(m,state,text)['exhibitions'].values()))
    assert row['title']=='Paper, Light\nSecond line' and row['end_date']=='2030-05-01'
    for kind in ['manual','unsupported']:
        state=source(m,kind); hits=[]
        out=m.process_exhibition_action(state,dict(type='sync',source_id='gallery',current_date='2030-05-01'),fetch_text=lambda url:hits.append(url))
        assert hits==[] and out['exhibitions']=={}
        assert out['result']['manual_entry_required'] is True and out['result']['updated']==0

def test_ru_005_city_views_date_boundaries():
    m=load_solution(); state={'sources':{},'exhibitions':{}}
    records=[item('Closed',end='2030-04-30',url='/closed'),item('Today',end='2030-05-01',url='/today'),
             item('Boundary',end='2030-05-08',url='/boundary'),item('Later',end='2030-05-09',url='/later'),
             item('Upcoming',start='2030-05-02',end='2030-05-07',url='/upcoming')]
    for index,row in enumerate(records):
        key='fixture-'+str(index)
        state['exhibitions'][key]={**row,'url':'https://museum.example.test'+row['url'],'exhibition_id':key,'source_id':'fixture-source','museum':'Example Gallery','city':'Example City','status':'ongoing'}
    before=deepcopy(state)
    out=m.process_exhibition_action(state,dict(type='city_views',city='example city',current_date='2030-05-01'))['result']
    assert state==before
    statuses=dict(Closed='closed',Today='closing_soon',Boundary='closing_soon',Later='ongoing',Upcoming='upcoming')
    expected=sorted([{**row,'status':statuses[row['title']]} for row in state['exhibitions'].values()],key=lambda x:(x['start_date'],x['title'],x['url']))
    assert out['museums']==['Example Gallery']
    for view in ['timeline','calendar','gallery']: assert out[view]==expected
    assert {x['title'] for x in out['closing_soon']}=={'Today','Boundary'}
    assert {x['title']:x['status'] for x in out['timeline']}==dict(Closed='closed',Today='closing_soon',Boundary='closing_soon',Later='ongoing',Upcoming='upcoming')
    later=m.process_exhibition_action(state,dict(type='city_views',city='Example City',current_date='2030-05-10'))['result']
    assert later['closing_soon']==[] and all(r['status']=='closed' for r in later['timeline'])
    empty=m.process_exhibition_action(state,dict(type='city_views',city='Other City',current_date='2030-05-01'))['result']
    assert all(empty[key]==[] for key in ['timeline','calendar','gallery','museums','closing_soon'])


def test_ru_003_preserves_distinct_url_path_case():
    m=load_solution(); state=source(m)
    out=sync(m,state,json.dumps([item('Lowercase',url='/shows/paper'),item('Uppercase',url='/shows/Paper')]))
    assert len(out['exhibitions'])==2
    assert {r['url'] for r in out['exhibitions'].values()}=={'https://museum.example.test/shows/paper','https://museum.example.test/shows/Paper'}


def test_ru_004_actual_wire_formats():
    for kind in ['JSON','RSS','ics','html']:
        check_actual_wire_format(kind)

if __name__=='__main__':
    suite=unittest.TestSuite(unittest.FunctionTestCase(value) for name,value in sorted(globals().items()) if name.startswith('test_ru_') and callable(value))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
