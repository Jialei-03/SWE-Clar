from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import unquote
import json,secrets
from conftest import load_solution

@contextmanager
def provider(source=None,destination=None):
    rows=[] if source is None else deepcopy(source);target={} if destination is None else deepcopy(destination)
    secret=secrets.token_hex(24);requests=[];deliveries={};fail={'put':set(),'put_ack':set(),'outreach':False,'outreach_ack':False,'source':False}
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,value):self.send_response(status);self.end_headers();self.wfile.write(json.dumps(value).encode())
        def authenticated(self):return self.headers.get('Authorization')=='Bearer '+secret
        def do_GET(self):
            requests.append(('GET',self.path,None))
            if not self.authenticated():return self.reply(401,{})
            if self.path=='/source':return self.reply(200,{} if fail['source'] else rows)
            if self.path=='/destination':return self.reply(200,target)
            self.reply(404,{})
        def do_PUT(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(('PUT',self.path,body))
            if not self.authenticated() or not self.path.startswith('/destination/'):return self.reply(401,{})
            ident=unquote(self.path.removeprefix('/destination/'))
            if ident in fail['put']:return self.reply(503,{})
            if ident in fail['put_ack']:return self.reply(200,{'accepted':True,'source_id':'wrong'})
            target[ident]=body;self.reply(200,{'accepted':True,'source_id':ident})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(('POST',self.path,body,self.headers.get('Idempotency-Key')))
            if not self.authenticated() or self.path!='/outreach':return self.reply(401,{})
            if fail['outreach']:return self.reply(503,{})
            ident=body['delivery_id']
            if self.headers.get('Idempotency-Key')!=ident:return self.reply(400,{})
            deliveries.setdefault(ident,body)
            self.reply(200,{'accepted':True,'delivery_id':'wrong' if fail['outreach_ack'] else ident})
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    from candidate_proxy import ServiceConfig as PipelineClient
    base=f'http://127.0.0.1:{server.server_port}'
    client=PipelineClient({'source':base+'/source'},{'destination':base+'/destination'},base+'/outreach',secret)
    try:yield client,rows,target,requests,deliveries,fail,secret
    finally:server.shutdown();server.server_close();thread.join()

def run(m,state,client,kind='sync',**fields):
    event={'type':kind,'source':'source','destination':'destination',**fields};before=deepcopy((state,event));out=m.process_pipeline_event(state,event,client);assert (state,event)==before;return out

def test_ru_001_actual_source_destination_requests_and_inputs():
    m=load_solution()
    with provider([{'source_id':'row','name':'Synthetic row'}]) as (client,rows,target,requests,deliveries,fail,secret):
        state={'sources':{'source':[{'source_id':'fake','name':'Stale caller row'}]},'destinations':{'destination':{}}}
        out=run(m,state,client)
        assert target=={'row':{'source_id':'row','name':'Synthetic row','status':'new'}}
        assert sorted(r[:2] for r in requests)==sorted([('GET','/destination'),('GET','/source'),('PUT','/destination/row')])
        expected=dict(run_id='run:1',processed=1,created=1,updated=0,skipped=0,failed=0)
        assert {k:out['result'][k] for k in expected}==expected

def test_ru_002_real_upsert_failures_encoding_and_stable_ids():
    m=load_solution();source=[{'source_id':'a/b','name':'Encoded identifier'},{'source_id':2,'name':'Second'},{'source_id':True},{'name':'Missing'}]
    with provider(source) as (client,rows,target,requests,deliveries,fail,secret):
        fail['put'].add('2');out=run(m,{},client)
        assert out['result']['created']==1 and out['result']['failed']==3 and set(target)=={'a/b'}
        assert any(r[1]=='/destination/a%2Fb' for r in requests)
        fail['put'].clear();rows[:]=rows[:2];out=run(m,out,client)
        assert out['result']['created']==1 and out['result']['updated']==1 and len(target)==2
        prior=deepcopy(target);fail['put_ack'].add('2');rows[1]['name']='Rejected acknowledgement';out=run(m,out,client)
        assert out['result']['failed']==1 and target['2']==prior['2']
        assert out['destinations']['destination']['2']==prior['2']
    # A non-object cannot be a valid source row. The contract does not fix
    # whether its rejection is a malformed-read envelope or a failed-row report.
    with provider([None]) as (client,rows,target,requests,deliveries,fail,secret):
        out=run(m,{},client)
        if out.get('error'):
            assert out['error']['code']=='service_failed'
        else:
            assert {k:out['result'][k] for k in ['processed','created','updated','skipped','failed']}==dict(processed=1,created=0,updated=0,skipped=0,failed=1)
        assert target=={} and not any(r[0] in ('PUT','POST') for r in requests)

def test_ru_003_destination_owned_fields_from_fresh_service():
    m=load_solution();owned={'status':'contacted','assignee':'synthetic-owner','notes':'Synthetic note','first_contact_date':'2030-01-01','estimated_students':0,'annual_license_value':120.5}
    source=[{'source_id':'row','name':'New name',**{key:'source must not own this' for key in owned}}]
    with provider(source,{'row':{'source_id':'row','name':'Old name',**owned}}) as (client,rows,target,requests,deliveries,fail,secret):
        state={'destinations':{'destination':{'row':{'status':'stale'}}}};out=run(m,state,client)
        assert target['row']=={'source_id':'row','name':'New name',**owned}
        assert out['destinations']['destination']['row']==target['row']

def test_ru_004_outreach_acknowledgement_status_retry_and_manual_rows():
    m=load_solution();dest={'row':{'source_id':'row','email':'synthetic@example.test','status':'new'},'manual':{'source_id':'manual','status':'new'}}
    with provider(destination=dest) as (client,rows,target,requests,deliveries,fail,secret):
        fail['outreach']=True;state=run(m,{},client,'queue_outreach',source_id='row',channel='email',accepted=True)
        assert state['result']['failed']==1 and target['row']['status']=='new' and deliveries=={}
        fail['outreach']=False;fail['put'].add('row');state=run(m,state,client,'queue_outreach',source_id='row',channel='email')
        assert state['result']['failed']==1 and target['row']['status']=='new' and len(deliveries)==1 and state['outbox']==[]
        fail['put'].clear();state=run(m,state,client,'queue_outreach',source_id='row',channel='email')
        assert target['row']['status']=='queued' and len(deliveries)==1 and len(state['outbox'])==1
        posts=[r for r in requests if r[0]=='POST'];assert all(r[3]=='outreach:destination:row' and r[2]=={'delivery_id':'outreach:destination:row','email':'synthetic@example.test'} for r in posts)
        n=len(posts);state=run(m,state,client,'queue_outreach',source_id='row',channel='email');assert state['result']['skipped']==1
        for ident,channel in [('manual','email'),('manual','linkedin')]:state=run(m,state,client,'queue_outreach',source_id=ident,channel=channel)
        assert len([r for r in requests if r[0]=='POST'])==n and target['manual']['status']=='new'

def test_ru_005_credentials_prevalidation_and_accounting():
    m=load_solution();secret_value=secrets.token_hex(24)
    with provider([{'source_id':'row','nested':{' Authorization ':secret_value,'keep':'Synthetic'},'access_token':secret_value}],{'row':{'source_id':'row','status':'new','PASSWORD':secret_value}}) as (client,rows,target,requests,deliveries,fail,secret):
        initial={'credentials':{'token':secret_value},'extra':[{'refresh_token':secret_value,'client_secret':secret_value}]}
        denied=run(m,initial,client,run_id='');assert denied['error']['code']=='invalid_run_id' and requests==[]
        assert secret_value not in json.dumps(denied)
        out=run(m,initial,client,run_id='synthetic-run');serialized=json.dumps(out)
        assert secret not in serialized and secret_value not in serialized and secret_value not in json.dumps(target)
        assert target['row']['nested']=={'keep':'Synthetic'} and out['result']['run_id']=='synthetic-run'
        assert {k:out['result'][k] for k in ['processed','created','updated','skipped','failed']}==dict(processed=1,created=0,updated=1,skipped=0,failed=0)
        fail['source']=True;before=deepcopy(target);bad=run(m,out,client);assert bad['error']['code']=='service_failed' and target==before
