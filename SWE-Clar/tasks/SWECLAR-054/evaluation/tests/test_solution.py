from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs,urlsplit
import base64,json,secrets
from conftest import load_solution

URI='spotify:track:'+'A'*22

@contextmanager
def provider():
    config={'client_id':'synthetic-client','client_secret':secrets.token_hex(20),'redirect_uri':'https://callback.example.test/finish'}
    tokens={};requests=[];libraries={};failures=set()
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,value=None):
            self.send_response(status);self.end_headers()
            if value is not None:self.wfile.write(json.dumps(value).encode())
        def do_POST(self):
            fields=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            requests.append(('token',self.path,fields))
            expected='Basic '+base64.b64encode((config['client_id']+':'+config['client_secret']).encode()).decode()
            if self.path!='/api/token' or self.headers.get('Authorization')!=expected or fields.get('grant_type')!=['authorization_code'] or fields.get('redirect_uri')!=[config['redirect_uri']]:return self.respond(401,{'error':'invalid_client'})
            code=fields.get('code',[''])[0]
            if code not in {'listener-a','listener-b','missing-scope'}:return self.respond(400,{'error':'invalid_grant'})
            token=secrets.token_hex(24);scope='user-library-modify' if code!='missing-scope' else 'user-read-private'
            tokens[token]=(code,scope);self.respond(200,{'access_token':token,'token_type':'Bearer','scope':scope,'expires_in':3600})
        def authorization(self):return tokens.get(self.headers.get('Authorization','').removeprefix('Bearer '))
        def do_GET(self):
            auth=self.authorization();requests.append(('profile',self.path))
            if self.path!='/v1/me' or not auth:return self.respond(401,{'error':'unauthorized'})
            if 'profile:'+auth[0] in failures:return self.respond(503,{'error':'temporary_profile_failure'})
            self.respond(200,{'id':'synthetic-'+auth[0]})
        def do_PUT(self):
            auth=self.authorization();parsed=urlsplit(self.path);uris=parse_qs(parsed.query).get('uris')
            requests.append(('save',auth[0] if auth else None,parsed.path,uris))
            if parsed.path!='/v1/me/library' or not auth or auth[1]!='user-library-modify':return self.respond(403,{'error':'forbidden'})
            if auth[0] in failures:return self.respond(503,{'error':'synthetic temporary failure'})
            if 'ack204:'+auth[0] in failures:return self.respond(204)
            if uris!=[URI]:return self.respond(400,{'error':'invalid_uri'})
            libraries.setdefault(auth[0],set()).add(URI);self.respond(200)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield {**config,'token_url':f'http://127.0.0.1:{server.server_port}/api/token','api_base':f'http://127.0.0.1:{server.server_port}/v1'},requests,libraries,failures,tokens
    finally:server.shutdown();server.server_close();thread.join()

from candidate_proxy import client

def setup(m):
    state=m.process_presave_action({},dict(type='create_artist',artist_id='artist',name='Synthetic artist'))
    state=m.process_presave_action(state,dict(type='create_release',release_id='release',artist_id='artist',release_at=10,now=0,spotify_uri=URI))
    return m.process_presave_action(state,dict(type='publish_campaign',release_id='release',slug='example-song'))

def authorize(m,state,service,listener='listener-a',code=None):
    action=dict(type='authorize_listener',listener_id=listener,authorization_code=code or listener)
    before=deepcopy((state,action));out=m.process_presave_action(state,action,service)
    assert before==(state,action);return out

def presave(m,state,listener='listener-a',consent=True):
    return m.process_presave_action(state,dict(type='presave',listener_id=listener,slug='example-song',consent=consent))

def test_ru_001_real_authorization_and_no_credentials_in_state():
    m=load_solution()
    with provider() as (config,requests,libraries,failures,tokens):
        service=client(config);state=authorize(m,setup(m),service)
        assert [r[0] for r in requests]==['token','profile']
        assert state['listeners']['listener-a']['provider_user_id']=='synthetic-listener-a'
        serialized=json.dumps(state)
        assert config['client_secret'] not in serialized and all(token not in serialized for token in tokens)
        assert 'access_token' not in serialized

def test_ru_002_release_validation():
    m=load_solution();state=m.process_presave_action({},dict(type='create_artist',artist_id='artist'))
    valid=dict(type='create_release',release_id='release',artist_id='artist',release_at=10,now=0,spotify_uri=URI)
    for patch in [{'release_at':0},{'artist_id':'unknown'},{'spotify_uri':'spotify:track:'},{'spotify_uri':'spotify:track:x'},{'release_at':float('nan')},{'release_at':float('inf')},{'release_at':True},{'now':float('nan')}]:
        result=m.process_presave_action(state,{**valid,**patch});assert result['error']['code'] and result['releases']=={}
    created=m.process_presave_action(state,valid)
    assert m.process_presave_action(created,valid)['error']['code']

def test_ru_003_provider_scope_and_explicit_consent():
    m=load_solution()
    with provider() as (config,requests,libraries,failures,tokens):
        service=client(config);state=setup(m)
        denied=m.process_presave_action(state,dict(type='authorize_listener',listener_id='listener-a',authorization_code='missing-scope',scopes=['user-library-modify']),service)
        assert denied['error']['code'] and denied['listeners']=={}
        assert authorize(m,state,service,code='invalid-code')['error']['code']
        state=authorize(m,state,service)
        assert presave(m,state,consent=False)['error']['code']
        assert presave(m,state,listener='unknown')['error']['code']
        assert libraries=={}

def test_ru_004_campaign_and_presave_replays():
 m=load_solution();state=setup(m);state['listeners']['listener-a']={'provider_user_id':'synthetic-listener-a','scopes':['user-library-modify']}
 duplicate=m.process_presave_action(state,dict(type='publish_campaign',release_id='release',slug='another'));assert duplicate['error']['code']
 first=presave(m,state);second=presave(m,first)
 assert first['presaves']==second['presaves'] and all(first['result'][k]==second['result'][k] for k in ['slug','listener_id','consent','fulfilled']) and len(second['presaves'])==1
 another=m.process_presave_action(state,dict(type='create_release',release_id='another',artist_id='artist',release_at=20,now=0,spotify_uri=URI))
 assert m.process_presave_action(another,dict(type='publish_campaign',release_id='another',slug='example-song'))['error']['code']

def test_ru_005_actual_save_acknowledgement_retry_and_revocation():
    m=load_solution()
    with provider() as (config,requests,libraries,failures,tokens):
        service=client(config);state=setup(m)
        for listener in ['listener-a','listener-b']:state=presave(m,authorize(m,state,service,listener),listener)
        action=dict(type='fulfill',slug='example-song',now=9)
        assert m.process_presave_action(state,action,service)['error']['code'] and not libraries
        failures.add('listener-a');action['now']=10;before=deepcopy((state,action))
        first=m.process_presave_action(state,action,service)
        assert before==(state,action)
        assert_summary(first['result'],['listener-b'],[],['listener-a'])
        assert libraries=={'listener-b':{URI}}
        assert_saved_libraries(first,['listener-b'])
        assert first['presaves']['example-song:listener-a']['fulfilled'] is False
        failures.clear();second=m.process_presave_action(first,action,service)
        assert_summary(second['result'],['listener-a'],['listener-b'],[])
        assert libraries=={'listener-a':{URI},'listener-b':{URI}}
        assert_saved_libraries(second,['listener-a','listener-b'])
        saves=len([r for r in requests if r[0]=='save']);replayed=m.process_presave_action(second,action,service)
        assert replayed['result']['fulfilled']==[] and sorted(replayed['result']['skipped'])==['listener-a','listener-b']
        assert len([r for r in requests if r[0]=='save'])==saves
        assert_saved_libraries(replayed,['listener-a','listener-b'])
        revoked=deepcopy(state);revoked['listeners']['listener-a']['scopes']=[];revoked['presaves']['example-song:listener-b']['consent']=False
        out=m.process_presave_action(revoked,action,service)
        assert out['result']['fulfilled']==[] and sorted(out['result']['skipped'])==['listener-a','listener-b']
        assert len([r for r in requests if r[0]=='save'])==saves

def assert_saved_libraries(state,listeners):
    expected=set(listeners)
    for listener in ['listener-a','listener-b']:
        uris=state['libraries'].get(listener,[])
        # URI collections may be arrays or URI-keyed objects with metadata.
        assert isinstance(uris,(list,dict))
        assert list(uris)==([URI] if listener in expected else [])
        assert state['presaves']['example-song:'+listener]['fulfilled'] is (listener in expected)

def assert_summary(out,fulfilled,skipped,failed):
 assert out['track']==URI
 for key,want in [('fulfilled',fulfilled),('skipped',skipped),('failed',failed)]:assert sorted(out[key])==sorted(want)

def business(state):return {k:state.get(k,{}) for k in ['artists','listeners','releases','campaigns','presaves','libraries']}

def test_ru_002_time_uri_boundaries():
 m=load_solution();state=m.process_presave_action({},dict(type='create_artist',artist_id='a'))
 assert m.process_presave_action(state,dict(type='create_artist',artist_id='a'))['error']['code']
 valid=dict(type='create_release',release_id='r',artist_id='a',release_at=1,now=0,spotify_uri='spotify:track:'+'9b'*11)
 good=m.process_presave_action(state,valid);assert good['releases']['r']['spotify_uri']==valid['spotify_uri']
 for fields in [{'now':True},{'now':float('inf')},{'now':None},{'now':'0'},{'release_at':False},{'release_at':-1},{'spotify_uri':'spotify:track:'+'a'*23},{'spotify_uri':'spotify:track:'+'_'*22}]:
  out=m.process_presave_action(state,{**valid,**fields});assert out['error']['code'];assert business(out)==business(state)

def test_ru_003_profile_failure_and_strict_consent():
 m=load_solution()
 with provider() as (config,requests,libraries,failures,tokens):
  service=client(config);state=setup(m);failures.add('profile:listener-a')
  out=authorize(m,state,service);assert out['error']['code'] and business(out)==business(state)
  failures.clear();state=authorize(m,state,service)
  out=authorize(m,state,service,code='invalid-code');assert out['error']['code'] and business(out)==business(state)
  for value in [1,'yes',None,{},[]]:
   out=presave(m,state,consent=value);assert out['error']['code'] and business(out)==business(state)

def test_ru_005_non200_and_invalid_time():
 m=load_solution()
 with provider() as (config,requests,libraries,failures,tokens):
  service=client(config);state=presave(m,authorize(m,setup(m),service));before=business(state)
  for fields in [{'now':True},{'now':float('nan')},{'now':'10'},{'now':float('inf')},{'now':10,'slug':'absent'}]:
   out=m.process_presave_action(state,{'type':'fulfill','slug':'example-song',**fields},service);assert out['error']['code'] and business(out)==before
  failures.add('ack204:listener-a');out=m.process_presave_action(state,{'type':'fulfill','slug':'example-song','now':11},service)
  assert_summary(out['result'],[],[],['listener-a']);assert business(out)==before and libraries=={}
