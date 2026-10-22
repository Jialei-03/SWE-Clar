from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs,urlsplit
import base64,json,secrets

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
            self.respond(200,{'id':'synthetic-'+auth[0]})
        def do_PUT(self):
            auth=self.authorization();parsed=urlsplit(self.path);uris=parse_qs(parsed.query).get('uris')
            requests.append(('save',auth[0] if auth else None,parsed.path,uris))
            if parsed.path!='/v1/me/library' or not auth or auth[1]!='user-library-modify':return self.respond(403,{'error':'forbidden'})
            if auth[0] in failures:return self.respond(503,{'error':'synthetic temporary failure'})
            if uris!=[URI]:return self.respond(400,{'error':'invalid_uri'})
            libraries.setdefault(auth[0],set()).add(URI);self.respond(200)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield {**config,'token_url':f'http://127.0.0.1:{server.server_port}/api/token','api_base':f'http://127.0.0.1:{server.server_port}/v1'},requests,libraries,failures,tokens
    finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
 import time
 with provider() as (config,*_):
  print(json.dumps(config),flush=True)
  try:
   while True:time.sleep(3600)
  except KeyboardInterrupt:pass
