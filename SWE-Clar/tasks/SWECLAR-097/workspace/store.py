import sqlite3,json,urllib.request,hashlib,hmac,secrets
class Error(Exception):
 def __init__(self,code,status=400):self.code=code;self.status=status
class Store:
 def __init__(self,path,config):
  self.path=path;self.config=config
  with self.db() as db:
   db.executescript('CREATE TABLE IF NOT EXISTS wallets(user TEXT PRIMARY KEY,credits INTEGER NOT NULL CHECK(credits>=0));CREATE TABLE IF NOT EXISTS dates(id TEXT PRIMARY KEY,user TEXT,record TEXT);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);')
   for user in config['users']:db.execute('INSERT OR IGNORE INTO wallets VALUES(?,?)',(user['id'],user['credits']))
 def db(self):return sqlite3.connect(self.path,timeout=8)
 def login(self,a):
  user=next((u for u in self.config['users'] if u['username']==a.get('username')),None)
  if not user or not hmac.compare_digest(hashlib.scrypt(str(a.get('password','')).encode(),salt=bytes.fromhex(user['salt']),n=16384,r=8,p=1).hex(),user['password_hash']):raise Error('invalid_credentials',403)
  token=secrets.token_urlsafe(32)
  with self.db() as db:db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id']))
  return token
 def actor(self,token):
  with self.db() as db:r=db.execute('SELECT user FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  user=next((u for u in self.config['users'] if r and u['id']==r[0]),None)
  if not user:raise Error('auth_required',403)
  return {'id':user['id'],'name':user['name'],'latitude':user['latitude'],'longitude':user['longitude']}
 def http(self,path,body):
  request=urllib.request.Request(self.config['provider_url']+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+self.config['provider_token']})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=3) as r:return json.load(r)
  except Exception:raise Error('provider_unavailable',502)
 def places(self,q):
  result=self.http('/places/search',{'query':q})
  return [p for p in result['places'] if p['type'] in {'restaurant','bar','pub','coffee'} and q.casefold() in p['name'].casefold()]
 def selected(self,ident):
  p=self.http('/places/get',{'id':ident}).get('place')
  if not p or p['type'] not in {'restaurant','bar','pub','coffee'}:raise Error('missing_place',404)
  return p
 def me(self,user):
  with self.db() as db:credits=db.execute('SELECT credits FROM wallets WHERE user=?',(user,)).fetchone()[0];dates=[json.loads(x[0]) for x in db.execute('SELECT record FROM dates WHERE user=? ORDER BY rowid',(user,))]
  return {'credits':credits,'dates':dates,'matches':[m for m in self.config['matches'] if user in m['users']],'products':self.config['products']}
 def create(self,user,a,mode):raise Error('not_implemented',501)
