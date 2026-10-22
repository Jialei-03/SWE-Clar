"""Six independent behavioral gates for the frozen synthetic pipeline contract."""
from concurrent.futures import ThreadPoolExecutor
import csv,io,json,sys,traceback
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,'/public_tests')
from pipeline_support import Pipeline,AdapterService,CandidateFailure,run_as
from test_public import run as public_run

class Checks:
    def __init__(self):self.passed=0
    def require(self,condition,message):
        if not condition:raise CandidateFailure(message)
        self.passed+=1

def event(key='event-a',source='sales',customer='customer-a',booking='booking-a',amount=100,day='2024-02-29',revision=0):
    return dict(source=source,event_id=key,customer_id=customer,booking_id=booking,amount_cents=amount,date=day,revision=revision)
def command(c,p,op,error=None,**fields):
    rows=p.run([{'op':op,**fields}]);c.require(len(rows)==1,'Exactly one response per command');r=rows[0]
    if error:c.require(r.get('ok') is False and r.get('error',{}).get('code')==error,'Expected '+error);return r
    c.require(r.get('ok') is True,'Command '+op+' succeeds: '+str(r));return r['result']
def records(c,p):return command(c,p,'records')['records']
def extract(rows):return [{k:r[k] for k in event()} for r in rows]
def posts(service):return [r for r in service.requests() if r[0]=='POST']

def gate_one(c):
    public_run();c.require(True,'Actual visible CLI/CSV baseline')
    with Pipeline() as p:
        raw=b'[]\nnull\n\xff\n'+b'x'*262145+b'\n{"op":"status"}\n'
        r=p.run(raw=raw);c.require(len(r)==5 and all(x.get('error',{}).get('code')=='invalid_request' for x in r[:4]) and r[4]['ok'],'Invalid and oversized lines consumed without corrupting next command')
        command(c,p,'missing-op',error='unknown_operation')
        initial=command(c,p,'status');c.require(initial['record_count']==initial['pending_deliveries']==initial['delivered_count']==0,'New persistent namespace starts empty')

def gate_two(c):
    with Pipeline() as p:
        row=event(customer='Synthetic, "A"\n第二行',booking='=synthetic,booking')
        command(c,p,'ingest',records=[row]);c.require(command(c,p,'report')['event_count']==0,'No implicit snapshot refresh')
        snap=command(c,p,'refresh');report=command(c,p,'report');c.require(report['snapshot_version']==snap['version'] and report['total_cents']==100,'Report uses refreshed snapshot')
        path=str(p.project/'nested/report.csv');result=command(c,p,'export',path=path)
        parsed=list(csv.reader(io.StringIO(p.read('nested/report.csv'))))
        c.require(parsed==[['customer_id','booking_id','event_count','total_cents'],[row['customer_id'],row['booking_id'],'1','100']],'Actual CSV faithfully preserves special characters')
        c.require(result['path']==path and result['row_count']==1,'Export reports its actual artifact')
        c.require(command(c,p,'report')['total_cents']==100,'Snapshot persists across separate CLI processes')

def gate_three(c):
    with Pipeline() as p:
        first=event();second=event(source='other');r=command(c,p,'ingest',records=[first,second]);c.require(r['inserted']==2,'Identity uses source and event together')
        for bad in [event(amount=True),event(day='2023-02-29'),event(revision=False),event(customer=''),event(amount=1000000001)]:
            command(c,p,'ingest',records=[event('new'),bad],error='invalid_batch');c.require(len(records(c,p))==2,'Invalid tail rolls back preceding insert')
        command(c,p,'ingest',records=[event('new'),event(amount=99)],error='revision_conflict');c.require(len(records(c,p))==2,'Equal revision conflict is batch atomic')
        updated=event(revision=2,amount=-23,customer='changed',booking='new-booking')
        r=command(c,p,'ingest',records=[updated,updated]);c.require(r['updated']==1 and r['unchanged']==1,'In-batch sequential replay counters')
        actual=extract(records(c,p));c.require(actual==[updated,second],'Update retains insertion position and replaces full mutable content')
        command(c,p,'ingest',records=[event(revision=1)],error='revision_conflict')
        command(c,p,'ingest',records=[],error=None)
        with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(lambda revision:p.run([{'op':'ingest','records':[event(revision=revision)]}])[0],[3,4]))
        c.require(all(r['ok'] or r.get('error',{}).get('code')=='revision_conflict' for r in out),'Concurrent writers have defined conflict outcomes')
        c.require(records(c,p)[0]['revision']==4,'Older concurrent revision cannot overwrite newer')

def gate_four(c):
    with Pipeline() as p:
        c.require(command(c,p,'refresh',watermark='ignored')['version']==0,'Empty no-op snapshot remains zero')
        command(c,p,'ingest',records=[event()]);a=command(c,p,'refresh',watermark='first')
        b=command(c,p,'refresh',watermark='second');c.require(a==b,'No-op refresh preserves watermark and version')
        command(c,p,'refresh',watermark=False,error='invalid_request')
        command(c,p,'ingest',records=[event(amount=250,revision=1)])
        c.require(command(c,p,'report')['total_cents']==100,'Live revision cannot mutate cached report')
        changed=command(c,p,'refresh',watermark=None);c.require(changed['version']==a['version']+1 and changed['record_count']==1 and changed['watermark'] is None,'Same-count content update invalidates snapshot')
        c.require(command(c,p,'report')['total_cents']==250,'Explicit refresh updates cached values')
        command(c,p,'ingest',records=[event(amount=250,revision=1)]);c.require(command(c,p,'refresh',watermark='ignored')==changed,'Exact ingest replay is not snapshot change')

def gate_five(c):
    with Pipeline() as p:
        rows=[event('1',customer='B',booking='same',amount=110,day='2024-03-01'),event('2',customer='A',booking='same',amount=-10,day='2024-03-02'),event('3',customer='A',booking='same',amount=50,day='2024-03-01'),event('4',customer='A',booking='other',amount=0,day='2024-03-03')]
        command(c,p,'ingest',records=rows);command(c,p,'refresh')
        report=command(c,p,'report',start='2024-03-01',end='2024-03-02')
        expected=[{'customer_id':'A','booking_id':'same','event_count':2,'total_cents':40},{'customer_id':'B','booking_id':'same','event_count':1,'total_cents':110}]
        c.require([{k:b[k] for k in expected[0]} for b in report['bookings']]==expected and report['event_count']==3 and report['total_cents']==150,'Inclusive dates, pair grouping, refunds and codepoint ordering')
        single=command(c,p,'report',customer_id='A',start='2024-03-02',end='2024-03-02');c.require(single['event_count']==1 and single['total_cents']==-10,'Exact customer and inclusive single-day filter')
        unknown=command(c,p,'report',customer_id='missing');c.require(unknown['event_count']==0 and unknown['bookings']==[],'Unknown customer empty aggregate')
        path=str(p.project/'filtered.csv');command(c,p,'export',path=path,customer_id='A',start='2024-03-02',end='2024-03-02')
        original=p.read('filtered.csv');c.require(list(csv.reader(io.StringIO(original)))[1]==['A','same','1','-10'],'CSV uses actual filtered aggregate')
        command(c,p,'export',path=path,start='2024-03-03',end='2024-03-01',error='invalid_filter');c.require(p.read('filtered.csv')==original,'Invalid export preserves existing artifact')
        command(c,p,'export',path=str(p.project/'../outside.csv'),error='invalid_path')
        run_as(1000,"import os,sys;os.symlink(sys.argv[1],sys.argv[2])",p.project/'filtered.csv',p.project/'alias.csv')
        command(c,p,'export',path=str(p.project/'alias.csv'),error='invalid_path');c.require(p.read('filtered.csv')==original,'Symlink target protected')

def gate_six(c):
    with AdapterService() as adapter,Pipeline(adapter=adapter.url) as p:
        command(c,p,'ingest',records=[event()]);command(c,p,'refresh')
        key='发送\n /?#';queued=command(c,p,'queue',request_id=key,target='table')['delivery']
        expected_report=dict(customer_id=None,start=None,end=None,snapshot_version=1,event_count=1,total_cents=100,
                             bookings=[dict(customer_id='customer-a',booking_id='booking-a',event_count=1,total_cents=100)])
        actual=queued['envelope']['report']
        c.require(all(actual.get(k)==v for k,v in expected_report.items()),'Queued report contains the independently expected snapshot aggregate')
        c.require(queued['envelope']['request_id']==key and queued['envelope']['target']=='table','Envelope identity matches queue input')
        c.require(queued['status']=='pending' and queued['attempts']==0 and not posts(adapter),'Queue durably records envelope without network')
        command(c,p,'ingest',records=[event(revision=1,amount=222)]);command(c,p,'refresh')
        replay=command(c,p,'queue',request_id=key,target='table',customer_id=None)['delivery'];c.require(replay==queued,'Queue replay retains original snapshot across refresh')
        command(c,p,'queue',request_id=key,target='mail',error='request_conflict')
        command(c,p,'queue',request_id=key,target='table',customer_id='other',error='request_conflict')
        adapter.configure('lose_response');failed=command(c,p,'deliver',request_id=key,error='delivery_failed')['delivery']
        c.require(failed['status']=='pending' and failed['attempts']==1 and len(posts(adapter))==1,'Lost response records exactly one pending attempt')
        adapter.configure()
        with ThreadPoolExecutor(max_workers=3) as pool:out=list(pool.map(lambda _:p.run([{'op':'deliver','request_id':key}])[0],range(3)))
        c.require(all(r['ok'] and r['result']['delivery']['status']=='delivered' and r['result']['delivery']['attempts']==2 for r in out),'Concurrent retries serialize successful delivery')
        c.require(len(posts(adapter))==2,'Delivered replays make no new HTTP call')
        with urlopen(adapter.url+'/receipts/table') as response:receipts=json.load(response)['receipts']
        c.require(receipts==[queued['envelope']],'Actual external receipt keeps old envelope exactly once')
        for mode in ['bad_ack','accepted_false','unavailable']:
            q=command(c,p,'queue',request_id=mode,target='mail')['delivery'];adapter.configure(mode)
            failure=command(c,p,'deliver',request_id=mode,error='delivery_failed')['delivery'];c.require(failure['status']=='pending' and failure['attempts']==1,'Incorrect acknowledgement cannot mark delivered')
        adapter.configure();before=len(posts(adapter));command(c,p,'deliver',request_id='not-found',error='not_found');c.require(len(posts(adapter))==before,'Unknown delivery never contacts connector')

GATES=[gate_one,gate_two,gate_three,gate_four,gate_five,gate_six]
def main():
    results=[];errors=[]
    for index,gate in enumerate(GATES,1):
        c=Checks();row={'ru_id':f'RU-{index:03d}','passed':False}
        try:gate(c);row.update(passed=True,detail='All executable checks passed')
        except (AssertionError,KeyError,ValueError,TypeError,IndexError) as error:row['detail']=type(error).__name__+': '+str(error)
        except Exception:row['detail']='Unattributed evaluator/environment error';errors.append(traceback.format_exc())
        row['checks_passed']=c.passed;results.append(row)
    print(json.dumps({'harness_ok':not errors,'results':results,'infrastructure_errors':errors}));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
