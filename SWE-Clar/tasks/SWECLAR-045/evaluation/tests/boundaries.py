from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import json
import os,subprocess,sys,uuid
from pathlib import Path
from candidate_proxy import call

def setup():
    s={}
    for a in [{'type':'register_terminal','imei':'t','name':'Primary terminal'},{'type':'register_terminal','imei':'other','name':'Other terminal'},{'type':'create_customer','customer_id':'u','name':'First customer'},{'type':'activate_card','card_id':'c','customer_id':'u'}]:
        s=call(s,a)
        assert not s.get('error'), 'Valid entity setup was rejected'
    return s
def event(kind,eid,amount,**kw):
    fields={'type':kind,'event_id':eid,'amount':amount,'card_id':'c','terminal_imei':'t','payment_method':'cash','product':'sample'}
    if kind=='sale':fields['timestamp']=0
    return {**fields,**kw}
def rejected(state,action):
    out=call(state,action);assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
    for key,value in state.items():assert out[key]==value

def ru001():
    state=setup();state['meta']={'nested':[1]};out=call(state,{'type':'report'})
    assert out['meta']==state['meta']
    assert out==call(deepcopy(state),{'type':'report'})
    root=Path(os.environ['CANDIDATE_ROOT']);database='/tmp/ledger-'+uuid.uuid4().hex+'.db'
    def worker(args,**kwargs):
        p=subprocess.run(args,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=15,**kwargs)
        assert p.returncode==0,p.stderr[-800:]
        return p.stdout
    try:
        state=call(state,event('topup','stored',1.25))
        value={'state':state,'action':{'type':'sync','terminal_imei':'t'}}
        command=[sys.executable,str(root/'cli.py'),'--server-db',database]
        first=json.loads(worker(command,input=json.dumps(value)))
        assert first['pending']['t']==[]
        code='import sqlite3,json,sys; db=sqlite3.connect(sys.argv[1]); print(json.dumps([json.loads(r[0]) for r in db.execute("SELECT body FROM events")]))'
        rows=json.loads(worker([sys.executable,'-c',code,database]));assert rows==state['pending']['t']
        replay=json.loads(worker(command,input=json.dumps(value)))
        assert replay['pending']['t']==[]
        assert json.loads(worker([sys.executable,'-c',code,database]))==rows
    finally:worker([sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).unlink(missing_ok=True)',database])
def ru002():
    s=setup()
    for action in [{'type':'register_terminal','imei':' ','name':'Invalid ID'},{'type':'register_terminal','imei':'t','name':'Duplicate terminal'},{'type':'create_customer','customer_id':'u','name':'Duplicate customer'},{'type':'activate_card','card_id':'other','customer_id':'u'},{'type':'activate_card','card_id':'fresh','customer_id':'missing'}]:rejected(s,action)
def ru003():
    s=setup()
    for amount in [0,-1,True,0.001,float('inf'),float('nan')]:rejected(s,event('topup','bad',amount))
    s=call(s,event('topup','one',0.3));s=call(s,event('sale','two',0.1))
    assert s['cards']['c']['balance']==0.2
    assert call(s,event('sale','two',0.1))==s
    rejected(s,event('sale','two',0.2));rejected(s,event('sale','new',0.21))
    rejected(s,event('refund','r',0.09,sale_event_id='two'))
    s=call(s,{'type':'create_customer','customer_id':'other-customer','name':'Other customer'})
    s=call(s,{'type':'activate_card','card_id':'other-card','customer_id':'other-customer'})
    assert s['cards']['other-card']['balance']==0
    rejected(s,event('refund','wrong-card',0.1,sale_event_id='two',card_id='other-card'))
    s=call(s,event('refund','r',0.1,sale_event_id='two'));assert s['cards']['c']['balance']==0.3
    rejected(s,event('refund','repeat',0.1,sale_event_id='two'))
def ru004():
    s=call(setup(),event('topup','one',3));s=call(s,event('topup','two',2))
    s=call(s,event('topup','other-terminal',1,terminal_imei='other'))
    def fail(rows):raise OSError('offline')
    out=call(s,{'type':'sync','terminal_imei':'t'},upload_events=fail)
    assert out.get('error')
    for key,value in s.items():assert out[key]==value
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(value)
            body=json.dumps({'accepted_ids':['one','unknown'],'conflicting_ids':['two']}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:out=call(s,{'type':'sync','terminal_imei':'t','sync_url':f'http://127.0.0.1:{server.server_port}/sync'})
    finally:server.shutdown();server.server_close();thread.join()
    assert seen==[{'events':s['pending']['t']}]
    assert [r['event_id'] for r in out['server_ledger']]==['one']
    assert [r['event_id'] for r in out['pending']['t']]==['two'] and out['pending']['other']==s['pending']['other']
    final=call(out,{'type':'sync','terminal_imei':'t'},upload_events=lambda rows:{'accepted_ids':['one','two','two']})
    assert [r['event_id'] for r in final['server_ledger']]==['one','two'] and final['pending']['t']==[]
def ru005():
    records=[{'event_id':str(i),'kind':'topup','amount':0.1,'payment_method':'cash'} for i in range(3)]
    out=call({'server_ledger':records},{'type':'report'})['result']
    assert out['credit_purchased']==0.3 and out['total_sales']==0 and out['refunds_by_payment_method']=={'cash':0,'card':0}
