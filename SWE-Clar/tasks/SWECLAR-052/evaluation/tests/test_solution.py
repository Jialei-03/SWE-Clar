from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs
import base64,json,secrets
from conftest import load_solution

@contextmanager
def provider():
    config={'client_id':'synthetic-client','client_secret':secrets.token_hex(20),'redirect_uri':'https://callback.example.test/complete'}
    requests=[];tokens={};failure={'conversion':False,'ack':False,'profile':False}
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,data):
            self.send_response(status);self.end_headers();self.wfile.write(json.dumps(data).encode())
        def do_POST(self):
            body=self.rfile.read(int(self.headers.get('Content-Length',0)));requests.append(('POST',self.path,body,self.headers.get('Idempotency-Key')))
            if self.path=='/token':
                fields=parse_qs(body.decode());auth='Basic '+base64.b64encode((config['client_id']+':'+config['client_secret']).encode()).decode()
                if self.headers.get('Authorization')!=auth or fields.get('grant_type')!=['authorization_code'] or fields.get('redirect_uri')!=[config['redirect_uri']]:return self.reply(401,{})
                if fields.get('code')!=['synthetic-code']:return self.reply(400,{})
                token=secrets.token_hex(24);tokens[token]='synthetic-user';return self.reply(200,dict(access_token=token,token_type='Bearer'))
            if self.path in ['/meta','/tiktok']:
                data=json.loads(body)
                if failure['conversion']:return self.reply(503,{})
                ack=dict(accepted=failure.get('accepted',True),event_id='wrong' if failure['ack'] else data.get('event_id'))
                if failure.get('missing_accepted'):ack.pop('accepted')
                return self.reply(200,ack)
            self.reply(404,{})
        def do_GET(self):
            requests.append(('GET',self.path));token=self.headers.get('Authorization','').removeprefix('Bearer ')
            if self.path!='/me' or token not in tokens:return self.reply(401,{})
            self.reply(200,{} if failure['profile'] else {'id':tokens[token]})
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        yield {**config,'token_url':base+'/token','profile_url':base+'/me','conversion_urls':{'meta':base+'/meta','tiktok':base+'/tiktok'}},requests,tokens,failure
    finally:server.shutdown();server.server_close();thread.join()

def has_error(out):
    code=out.get('error',{}).get('code')
    return isinstance(code,str) and bool(code.strip())

def setup(m,config):
    from candidate_proxy import ServiceConfig as SmartlinkClient
    client=SmartlinkClient(**config)
    state=m.process_smartlink_event({'smartlinks':{'link':{}},'attribution_window':10},dict(type='oauth_start',state_token='synthetic-state',user_id='user'),client)
    return client,state

def authorized(m,client,state):return m.process_smartlink_event(state,dict(type='oauth_complete',state_token='synthetic-state',code='synthetic-code'),client)
def clicked(m,state):
    state=deepcopy(state);state.setdefault('smartlinks',{})['link']={'url':'https://music.example.test/listen'}
    return m.process_smartlink_event(state,dict(type='click',click_id='click',smartlink_id='link',destination='spotify',timestamp=100))
def streamed(m,state):return m.process_smartlink_event(state,dict(type='stream',stream_id='stream',click_id='click',user_id='user',timestamp=110))

def test_ru_001_inputs_and_actual_authorization_without_credentials():
    m=load_solution()
    with provider() as (config,requests,tokens,failure):
        client,state=setup(m,config);before=deepcopy(state);out=authorized(m,client,state)
        assert state==before and out['spotify_users']['user']['provider_user_id']=='synthetic-user'
        assert [r[:2] for r in requests]==[('POST','/token'),('GET','/me')]
        serialized=json.dumps(out)
        for secret in [config['client_secret'],'synthetic-code',*tokens]:assert secret not in serialized

def test_ru_002_callback_validation_failure_and_single_use():
    m=load_solution()
    with provider() as (config,requests,tokens,failure):
        client,state=setup(m,config)
        for token,code in [('unknown','synthetic-code'),('synthetic-state',''),('synthetic-state',None),('synthetic-state',55)]:
            out=m.process_smartlink_event(state,dict(type='oauth_complete',state_token=token,code=code),client)
            assert out['error']['code']=='invalid_oauth_callback' and requests==[]
        out=m.process_smartlink_event(state,dict(type='oauth_complete',state_token='synthetic-state',code='invalid'),client)
        assert out['error']['code']=='authorization_failed' and not out['oauth_states']['synthetic-state']['consumed']
        # Unauthorized is a business state, not a required empty-map encoding.
        assert not out.get('spotify_users',{}).get('user',{}).get('authorized',False)
        failure['profile']=True;out=authorized(m,client,state)
        assert out['error']['code']=='authorization_failed' and not out['oauth_states']['synthetic-state']['consumed']
        assert not out.get('spotify_users',{}).get('user',{}).get('authorized',False)
        failure['profile']=False;out=authorized(m,client,state);n=len(requests)
        assert out['oauth_states']['synthetic-state']['consumed']
        assert authorized(m,client,out)['error']['code']=='invalid_oauth_callback' and len(requests)==n
        assert has_error(m.process_smartlink_event(out,dict(type='oauth_start',state_token='synthetic-state',user_id='new')))

def test_ru_003_clicks_and_finite_timestamps():
    m=load_solution();state=clicked(m,{})
    assert state['clicks']['click']['timestamp']==100
    assert clicked(m,state)['result']['replayed'] is True and len(state['clicks'])==1
    for timestamp in [float('nan'),float('inf'),True,'100']:
        out=m.process_smartlink_event(state,dict(type='click',click_id='new',smartlink_id='link',destination='spotify',timestamp=timestamp))
        assert has_error(out) and 'new' not in out['clicks']
    assert has_error(m.process_smartlink_event(state,dict(type='click',click_id='new',smartlink_id='unknown',destination='spotify',timestamp=100)))

def test_ru_004_attribution_boundaries_and_authorization():
    m=load_solution()
    with provider() as (config,requests,tokens,failure):
        client,state=setup(m,config);state.update(spotify_users={'user':{'authorized':True}},clicks={'click':{'click_id':'click','timestamp':100}})
        for timestamp in [99,111,float('nan'),float('inf'),True]:
            out=m.process_smartlink_event(state,dict(type='stream',stream_id='bad',click_id='click',user_id='user',timestamp=timestamp))
            assert out['error']['code']=='unattributed_stream' and out['streams']=={}
        for timestamp in [100,110]:
            out=m.process_smartlink_event(state,dict(type='stream',stream_id='valid',click_id='click',user_id='user',timestamp=timestamp))
            assert out['streams']['valid']['attributed'] is True
        denied=deepcopy(state);denied['spotify_users']={}
        assert streamed(m,denied)['error']['code']=='unattributed_stream'

def test_ru_005_real_conversion_ack_retry_replay_and_totals():
    m=load_solution()
    with provider() as (config,requests,tokens,failure):
        client,state=setup(m,config);state.update(clicks={'click':{'click_id':'click','timestamp':100}},streams={'stream':{'stream_id':'stream','click_id':'click','attributed':True}})
        event=dict(type='conversion',platform='  MeTa ',event_id='conversion',stream_id='stream');before=deepcopy((state,event))
        for streams in [{},{'stream':{**state['streams']['stream'],'attributed':False}}]:
            ineligible={**deepcopy(state),'streams':streams};n=len(requests)
            denied=m.process_smartlink_event(ineligible,event,client)
            assert has_error(denied) and len(requests)==n
            assert denied.get('conversions',{})==ineligible.get('conversions',{})
            assert denied['streams']==streams
        for missing in [False,True]:
            failure['accepted']=False;failure['missing_accepted']=missing
            denied=m.process_smartlink_event(state,event,client)
            assert denied['error']['code']=='conversion_failed' and denied['conversions']=={}
        failure['accepted']=True;failure['missing_accepted']=False
        failure['conversion']=True;out=m.process_smartlink_event(denied,event,client)
        assert out['error']['code']=='conversion_failed' and out['conversions']=={} and before==(state,event)
        failure['conversion']=False;failure['ack']=True;out=m.process_smartlink_event(out,event,client)
        assert out['error']['code']=='conversion_failed' and out['conversions']=={}
        failure['ack']=False;out=m.process_smartlink_event(out,event,client)
        assert out['conversions']['meta:conversion']['stream_id']=='stream'
        request=requests[-1];assert request[:2]==('POST','/meta') and request[3]=='meta:conversion'
        assert all(json.loads(request[2])[k]==v for k,v in dict(event_id='conversion',platform='meta',stream_id='stream',click_id='click').items())
        n=len(requests);out=m.process_smartlink_event(out,{**event,'platform':'meta'},client)
        assert out['result']['replayed'] is True and len(requests)==n
        out=m.process_smartlink_event(out,{**event,'platform':'TikTok'},client);assert requests[-1][1]=='/tiktok'
        n=len(requests);bad=m.process_smartlink_event(out,{**event,'platform':'unsupported'},client)
        assert has_error(bad) and len(requests)==n
        totals=m.process_smartlink_event(out,dict(type='status'))['result']
        assert all(totals[k]==v for k,v in dict(clicks=1,attributed_streams=1,conversions=2).items())


def test_ru_001_cli_regression():
    import os,subprocess,sys
    p=subprocess.run([sys.executable,'/workspace/cli.py'],input=json.dumps({'state':{},'events':[{'type':'status'}]}),capture_output=True,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},timeout=15)
    assert p.returncode==0,p.stderr
    assert json.loads(p.stdout)['result']['clicks']==0
