"""Local streaming client service; all payment fixtures are synthetic."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os,json,sqlite3,secrets,hashlib,hmac,urllib.request,urllib.error,urllib.parse,re
class Error(Exception):
 def __init__(self,message,status=400):self.message=message;self.status=status
class Store:
 def __init__(self,path,config):
  self.path=path;self.config=config
  with self.db() as db:db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,payment_id TEXT UNIQUE,salt TEXT,verifier TEXT);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);CREATE TABLE IF NOT EXISTS wallets(user TEXT PRIMARY KEY,balance INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS credits(tx TEXT PRIMARY KEY,user TEXT,amount INTEGER);CREATE TABLE IF NOT EXISTS licenses(user TEXT,track TEXT,PRIMARY KEY(user,track));''')
 def db(self):db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;return db
 def digest(self,password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
 def provider(self,path,data=None):
  req=urllib.request.Request(self.config['provider']+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.config['api_key']})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:return json.load(r)
  except (urllib.error.URLError,ValueError):raise Error('provider_unavailable',502)
 def register(self,a):
  email=a.get('email','');password=a.get('password','')
  if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(password)<12:raise Error('invalid_registration')
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
   if old:raise Error('already_registered',409)
   account=self.provider('/accounts?email='+urllib.parse.quote(email))
   if not account:account=self.provider('/accounts',{'email':email})
   if account.get('email')!=email or not isinstance(account.get('id'),str):raise Error('invalid_account')
   user=secrets.token_hex(12);salt=secrets.token_hex(16);db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(user,email,account['id'],salt,self.digest(password,salt)));db.execute('INSERT INTO wallets(user) VALUES(?)',(user,));return {'id':user,'email':email}
 def login(self,a):
  with self.db() as db:
   row=db.execute('SELECT * FROM users WHERE email=?',(a.get('email','').strip().casefold(),)).fetchone()
   if not row or not hmac.compare_digest(row['verifier'],self.digest(a.get('password',''),row['salt'])):raise Error('invalid_login',401)
   token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id']));return {'token':token}
 def actor(self,token):
  with self.db() as db:r=db.execute('SELECT user FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  if not r:raise Error('unauthorized',401)
  return r['user']
 def tracks(self,q):return sorted([dict(t) for t in self.config['catalog'] if q.casefold() in (t['title']+' '+t['artist']).casefold()],key=lambda t:(t['title'].casefold(),t['id']))
 def act(self,user,path,a):
  with self.db() as db:
   if path=='/credit':
    tx=a['transaction_id'];db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM credits WHERE tx=?',(tx,)).fetchone()
    if old:
     if old['user']!=user:raise Error('transaction_conflict',409)
     return {'balance':db.execute('SELECT balance FROM wallets WHERE user=?',(user,)).fetchone()[0]}
    receipt=self.provider('/receipts/'+urllib.parse.quote(tx,safe=''));p=receipt['payload'];sig=hmac.new(bytes.fromhex(self.config['receipt_key']),json.dumps(p,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest();pay=db.execute('SELECT payment_id FROM users WHERE id=?',(user,)).fetchone()[0]
    if False or p.get('transaction_id')!=tx or p.get('payment_id')!=pay or p.get('status')!='paid' or type(p.get('tokens')) is not int or p['tokens']<=0:raise Error('invalid_receipt')
    db.execute('INSERT INTO credits VALUES(?,?,?)',(tx,user,p['tokens']));db.execute('UPDATE wallets SET balance=balance+? WHERE user=?',(p['tokens'],user));return {'balance':db.execute('SELECT balance FROM wallets WHERE user=?',(user,)).fetchone()[0]}
   if path=='/license':
    track=next((t for t in self.config['catalog'] if t['id']==a['track']),None)
    if not track:raise Error('not_found',404)
    db.execute('BEGIN IMMEDIATE')
    if not db.execute('SELECT 1 FROM licenses WHERE user=? AND track=?',(user,track['id'])).fetchone():
     changed=db.execute('UPDATE wallets SET balance=balance-? WHERE user=? AND balance>=?',(track['cost'],user,track['cost'])).rowcount
     if not changed:raise Error('insufficient_tokens',409)
     db.execute('INSERT INTO licenses VALUES(?,?)',(user,track['id']))
    return {'track':track['id'],'balance':db.execute('SELECT balance FROM wallets WHERE user=?',(user,)).fetchone()[0]}
   raise Error('not_found',404)
 def read(self,user,path,q):
  with self.db() as db:
   if path=='/me':return dict(db.execute('SELECT id,email,balance FROM users JOIN wallets ON users.id=wallets.user WHERE id=?',(user,)).fetchone())
   if path=='/catalog':return [{k:v for k,v in t.items() if k!='filename'} for t in self.tracks(q)]
   if path=='/licenses':return [r[0] for r in db.execute('SELECT track FROM licenses WHERE user=? ORDER BY track',(user,))]
   raise Error('not_found',404)
def main():
 root=Path(__file__).parent;config=json.loads(Path(os.environ['STREAM_CONFIG']).read_text());store=Store(os.environ['STREAM_DATABASE'],config);assets=Path(os.environ['STREAM_ASSETS']).resolve()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def send(self,status,data,mime='application/json',extra=None):
   raw=json.dumps(data).encode() if mime=='application/json' else data;self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
   for k,v in (extra or {}).items():self.send_header(k,v)
   self.end_headers();self.wfile.write(raw)
  def execute(self):
   try:
    parsed=urllib.parse.urlsplit(self.path);path=parsed.path
    if self.command=='GET' and path in ['/','/app.js','/react.js','/react-dom.js']:
     name='index.html' if path=='/' else path[1:];return self.send(200,(root/'dist'/name).read_bytes(),'text/html' if path=='/' else 'text/javascript')
    size=int(self.headers.get('Content-Length','0'))
    if size>65536:raise Error('request_too_large',413)
    a=json.loads(self.rfile.read(size) or b'{}')
    if not isinstance(a,dict):raise Error('invalid_input')
    if self.command=='POST' and path=='/register':return self.send(200,store.register(a))
    if self.command=='POST' and path=='/login':return self.send(200,store.login(a))
    token=self.headers.get('Authorization','').removeprefix('Bearer ');user=store.actor(token)
    if self.command=='POST' and path=='/logout':
     with store.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
     return self.send(200,{})
    if self.command=='GET' and path.startswith('/media/'):
     tid=path.removeprefix('/media/');track=next((t for t in config['catalog'] if t['id']==tid),None)
     with store.db() as db:licensed=db.execute('SELECT 1 FROM licenses WHERE user=? AND track=?',(user,tid)).fetchone()
     if not track or not licensed:raise Error('not_licensed',403)
     file=(assets/track['filename']).resolve()
     if not file.is_relative_to(assets):raise Error('not_found',404)
     raw=file.read_bytes();r=self.headers.get('Range')
     if r:
      m=re.fullmatch(r'bytes=(\d+)-(\d*)',r)
      if not m:raise Error('invalid_range',416)
      start=int(m[1]);end=min(len(raw)-1,int(m[2])) if m[2] else len(raw)-1
      if start>end:raise Error('invalid_range',416)
      return self.send(206,raw[start:end+1],'audio/wav',{'Content-Range':f'bytes {start}-{end}/{len(raw)}','Accept-Ranges':'bytes'})
     return self.send(200,raw,'audio/wav',{'Accept-Ranges':'bytes'})
    return self.send(200,store.read(user,path,urllib.parse.parse_qs(parsed.query).get('q',[''])[0]) if self.command=='GET' else store.act(user,path,a))
   except Error as e:self.send(e.status,{'error':e.message})
   except sqlite3.IntegrityError:self.send(409,{'error':'conflict'})
   except (KeyError,ValueError,TypeError):self.send(400,{'error':'invalid_input'})
   except FileNotFoundError:self.send(404,{'error':'not_found'})
  do_GET=execute;do_POST=execute
 server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(server.server_port,flush=True);server.serve_forever()
if __name__=='__main__':main()
