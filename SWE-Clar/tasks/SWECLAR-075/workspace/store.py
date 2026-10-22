import sqlite3,json,secrets,hashlib,hmac,math,base64
from datetime import datetime,timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
class Error(Exception):
 def __init__(self,code,status=400):self.code=code;self.status=status

def distance(lat,lon,site):
 lat=float(lat);lon=float(lon)
 if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:raise Error('invalid_location')
 p1,p2=map(math.radians,[lat,site['latitude']]);dp=p2-p1;dl=math.radians(site['longitude']-lon)
 a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 6371008.8*2*math.asin(math.sqrt(min(1,max(0,a))))
class Store:
 def __init__(self,path,config,clock=None):
  self.path=path;self.config=config;self.key=bytes.fromhex(config['encryption_key']);self.crypto=AESGCM(self.key);self.clock=clock or (lambda:datetime.now(timezone.utc).timestamp())
  with self.db() as db:db.executescript('CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, lookup TEXT UNIQUE,email TEXT,salt TEXT,verifier TEXT,active INTEGER);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);CREATE TABLE IF NOT EXISTS intervals(id TEXT PRIMARY KEY,user TEXT,record TEXT,open INTEGER);CREATE UNIQUE INDEX IF NOT EXISTS one_open ON intervals(user) WHERE open=1;')
 def db(self):return sqlite3.connect(self.path,timeout=5)
 def seal(self,data):
  nonce=secrets.token_bytes(12);return base64.b64encode(nonce+self.crypto.encrypt(nonce,json.dumps(data).encode(),b'checkin-fixture')).decode()
 def unseal(self,data):
  blob=base64.b64decode(data);return json.loads(self.crypto.decrypt(blob[:12],blob[12:],b'checkin-fixture'))
 def lookup(self,email):return hmac.new(self.key,email.strip().lower().encode(),hashlib.sha256).hexdigest()
 def register(self,a):
  email=str(a.get('email','')).strip().lower();password=a.get('password','')
  if '@' not in email or not isinstance(password,str) or len(password)<8:raise Error('invalid_account')
  ident=secrets.token_hex(12);salt=secrets.token_bytes(16);verifier=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
  try:
   with self.db() as db:db.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(ident,self.lookup(email),self.seal(email),salt.hex(),verifier))
  except sqlite3.IntegrityError:raise Error('duplicate_account',409)
  return {'id':ident,'email':email}
 def login(self,a):
  with self.db() as db:
   row=db.execute('SELECT id,salt,verifier,active FROM users WHERE lookup=?',(self.lookup(str(a.get('email',''))),)).fetchone()
   if not row or not row[3] or not hmac.compare_digest(hashlib.scrypt(str(a.get('password','')).encode(),salt=bytes.fromhex(row[1]),n=16384,r=8,p=1).hex(),row[2]):raise Error('invalid_credentials',403)
   token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),row[0]));return token
 def actor(self,token):
  with self.db() as db:r=db.execute('SELECT u.id,u.email FROM sessions s JOIN users u ON u.id=s.user WHERE s.hash=? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  if not r:raise Error('auth_required',403)
  return {'id':r[0],'email':self.unseal(r[1])}
 def logout(self,token):
  with self.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
  return {'ok':True}
 def checkin(self,user,a):raise Error('not_implemented',501)
 def checkout(self,user):
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT id,record FROM intervals WHERE user=? AND open=1',(user,)).fetchone()
   if not row:raise Error('no_open_interval',409)
   r=self.unseal(row[1]);now=self.clock()
   if now<r['started_at']:raise Error('clock_regression',409)
   r.update(ended_at=now,duration_seconds=now-r['started_at']);db.execute('UPDATE intervals SET record=?,open=0 WHERE id=?',(self.seal(r),row[0]));return r
 def history(self,user):
  with self.db() as db:rows=[self.unseal(x[0]) for x in db.execute('SELECT record FROM intervals WHERE user=? ORDER BY rowid',(user,))]
  return rows
