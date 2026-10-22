from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import csv,io,math
from conftest import load_solution

def base():return {'categories':{'c':{'name':'Example category'}},'suggestions':{'garden':['Garden tools','garden tools','Garden plants']}}
def wire(rows):
    buffer=io.StringIO();writer=csv.writer(buffer);writer.writerow(['trend_id','keyword','month','count']);writer.writerows(rows);return buffer.getvalue()
def ingest(m,state,rows,**extra):
    a=dict(type='sync_source',category_id='c',url='https://metrics.example.test/data.csv',**extra);before=deepcopy((state,a));seen=[]
    def fetch(url):seen.append(url);return wire(rows)
    out=m.process_trend_action(state,a,fetch_text=fetch)
    assert before==(state,a) and seen==[a['url']]
    return out
def add(m,state,tid,growth):return ingest(m,state,[(tid,tid,'2030-01',1000),(tid,tid,'2030-02',1000+growth*10)],growth=9999)

def test_ru_001_real_http_and_atomic_source_validation():
    m=load_solution();seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(wire([('example','Garden, tools','2030-01',100),('example','Garden, tools','2030-02',125)]).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    state=base();before=deepcopy(state)
    try:
        out=m.process_trend_action(state,dict(type='sync_source',category_id='c',url=f'http://127.0.0.1:{server.server_port}/measurements',growth=-100))
        assert seen==['/measurements'] and state==before
        assert out['trends']['example']['growth']==25 and out['trends']['example']['keyword']=='Garden, tools'
    finally:server.shutdown();server.server_close();thread.join()
    for rows in [[('good','Good','2030-01',1),('bad','Bad','2030-13',2)],[('bad','Bad','2030-01',-1)],[('bad','Bad','2030-01','NaN')],[('bad','Bad','2030-01',1),('bad','Bad','2030-01',2)]]:
        rejected=ingest(m,out,rows);assert rejected['error']['code']=='invalid_source' and rejected['trends']==out['trends']
    def failed(url):raise OSError('Synthetic source failure')
    result=m.process_trend_action(out,dict(type='sync_source',category_id='c',url='https://metrics.example.test/fail'),fetch_text=failed)
    assert result['error']['code']=='fetch_failed' and result['trends']==out['trends']

def test_ru_002_computed_growth_thresholds_history_and_baselines():
    m=load_solution();state=base()
    for i,(growth,label) in enumerate([(31,'hot'),(30,'rising'),(15,'rising'),(14.9,'regular'),(0,'regular'),(-1,'declining')]):
        tid=str(i);state=add(m,state,tid,growth);row=state['trends'][tid]
        assert math.isclose(row['growth'],growth,rel_tol=1e-9,abs_tol=1e-9) and row['classification']==label
    months=[f'2029-{m:02}' for m in range(1,13)]+['2030-01','2030-02']
    rows=[('history','History',month,100+i) for i,month in enumerate(months)]
    state=ingest(m,state,list(reversed(rows)));history=state['trends']['history']['history']
    assert history==[{'month':month,'count':100+i} for i,month in enumerate(months) if i>=2]
    assert math.isclose(state['trends']['history']['growth'],100/112,rel_tol=1e-9)
    assert ingest(m,state,list(reversed(rows)))==state
    for tid,counts,expected in [('none',[2],None),('zero',[0,0],0),('new',[0,3],None)]:
        state=ingest(m,state,[(tid,tid,f'2030-0{i+1}',v) for i,v in enumerate(counts)]);row=state['trends'][tid]
        assert row['growth']==expected
        assert row['classification']==('insufficient_baseline' if expected is None else 'regular')

def test_ru_003_category_sorting_uses_computed_growth():
    m=load_solution();state=add(m,base(),'first',5);state=add(m,state,'second',20)
    state=ingest(m,state,[('unknown','Unknown','2030-01',0)])
    out=m.process_trend_action(state,dict(type='category_view',category_ids=['c']))
    assert [r['trend_id'] for r in out['result']['trends']]==['second','first','unknown']
    assert m.process_trend_action(state,dict(type='category_view',category_ids=['c','other']))['error']['code']

def test_ru_004_watch_and_discovery():
    m=load_solution();state=add(m,base(),'first',2);action=dict(type='watch',user_id='synthetic-user',trend_id='first')
    state=m.process_trend_action(state,action);state=m.process_trend_action(state,action)
    assert state['result']['trend_ids']==['first']
    assert m.process_trend_action(state,dict(type='discover',seed=' GARDEN '))['result']['suggestions']==['Garden tools','Garden plants']
    out=m.process_trend_action(state,{**action,'type':'unwatch'});assert out['result']['trend_ids']==[]

def test_ru_005_candidate_curation_is_bounded_and_once_per_month():
    m=load_solution();state=add(m,base(),'existing',2)
    # Check the cap independently of deduplication. The contract does not say
    # whether skipped entries consume the 25-candidate processing budget.
    candidates=[f'candidate {i}' for i in range(30)]
    action=dict(type='generate_keywords',category_id='c',month='2030-03',candidates=candidates);before=deepcopy(action)
    out=m.process_trend_action(state,action)
    assert action==before and len(out['result']['added_ids'])==25
    assert all(out['trends'][tid]['keyword'].casefold()!='existing' for tid in out['result']['added_ids'])
    assert m.process_trend_action(out,action)['error']['code']
    # With fewer than 25 inputs, existing and intra-batch duplicates must skip
    # under either permitted limit interpretation, preserving supplied order.
    small={**action,'candidates':['existing','EXISTING','new','NEW','second']}
    unique=m.process_trend_action(state,small)
    assert [unique['trends'][tid]['keyword'] for tid in unique['result']['added_ids']]==['new','second']


def test_ru_005_generated_ids_cannot_overwrite_existing_measurements():
    m=load_solution();state=add(m,base(),'c-2',5);before=deepcopy(state['trends']['c-2'])
    out=m.process_trend_action(state,dict(type='generate_keywords',category_id='c',month='2030-03',candidates=['new keyword']))
    assert out['trends']['c-2']==before
    assert out['result']['added_ids']!=['c-2'] and len(out['trends'])==2
