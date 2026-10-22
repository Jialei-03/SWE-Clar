"""Synthetic property-report SaaS component with local storage and payment fixture."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import BytesIO
import base64,hashlib,hmac,json,os,secrets,sqlite3,urllib.request,urllib.error
from PIL import Image,ImageOps
from reportlab.pdfgen import canvas
class Error(Exception):
 def __init__(self,message,status=400):self.message=message;self.status=status
class Store:
 def __init__(self,path,config):
  self.path=path;self.config=config
  with self.db() as db:db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,salt TEXT,verifier TEXT,trial INTEGER DEFAULT 0,plan TEXT);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,user TEXT,plan TEXT);CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY,user TEXT,name TEXT);CREATE TABLE IF NOT EXISTS content(id TEXT PRIMARY KEY,room TEXT,title TEXT,details TEXT,complete INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,content TEXT,kind TEXT,data BLOB);''')
 def db(self):
  db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;return db
 def verifier(self,password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
 def auth(self,path,a):
  email=a.get('email','').strip().lower();password=a.get('password','')
  if not email or '@' not in email or len(password)<8:raise Error('invalid_credentials')
  with self.db() as db:
   if path=='/register':
    ident=secrets.token_hex(12);salt=secrets.token_hex(16);db.execute('INSERT INTO users(id,email,salt,verifier) VALUES(?,?,?,?)',(ident,email,salt,self.verifier(password,salt)))
   user=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
   if not user or not secrets.compare_digest(user['verifier'],self.verifier(password,user['salt'])):raise Error('invalid_credentials',401)
   token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id']));return {'token':token,'id':user['id']}
 def user(self,token):
  with self.db() as db:u=db.execute('SELECT u.id,u.email,u.trial,u.plan FROM users u JOIN sessions s ON s.user=u.id WHERE s.hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  if not u:raise Error('unauthorized',401)
  return dict(u)
 def owner(self,db,user,content):
  row=db.execute('SELECT c.*,r.user,r.name room_name FROM content c JOIN rooms r ON c.room=r.id WHERE c.id=?',(content,)).fetchone()
  if not row or row['user']!=user['id']:raise Error('not_found',404)
  return dict(row)
 def act(self,user,path,a):
  with self.db() as db:
   if path=='/trial':
    db.execute('BEGIN IMMEDIATE');changed=db.execute('UPDATE users SET trial=1 WHERE id=? AND trial=0 AND plan IS NULL',(user['id'],)).rowcount
    if not changed:raise Error('trial_unavailable',409)
    return {'trial':True}
   if path=='/activate':
    payment=a['payment_id'];url=self.config['provider']+'/receipts/'+urllib.parse.quote(payment,safe='');opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:receipt=json.load(opener.open(url,timeout=5))
    except (urllib.error.URLError,ValueError):raise Error('provider_unavailable',502)
    payload=receipt['payload'];encoded=json.dumps(payload,sort_keys=True,separators=(',',':')).encode();signature=hmac.new(bytes.fromhex(self.config['provider_key']),encoded,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,receipt.get('signature','')):raise Error('invalid_receipt')
    plan=self.config['plans'].get(payload.get('plan'))
    if not plan or payload.get('id')!=payment or payload.get('user')!=user['id'] or payload.get('status')!='paid' or payload.get('amount')!=plan['amount'] or payload.get('currency')!=plan['currency']:raise Error('invalid_receipt')
    db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM payments WHERE id=?',(payment,)).fetchone()
    if old and (old['user']!=user['id'] or old['plan']!=payload['plan']):raise Error('payment_conflict',409)
    if not old:db.execute('INSERT INTO payments VALUES(?,?,?)',(payment,user['id'],payload['plan']))
    db.execute('UPDATE users SET plan=? WHERE id=?',(payload['plan'],user['id']));return {'plan':payload['plan']}
   if not (user['trial'] or user['plan']):raise Error('access_required',403)
   if path=='/rooms':
    if not a['name'].strip():raise Error('name_required')
    db.execute('INSERT INTO rooms VALUES(?,?,?)',(a['id'],user['id'],a['name']));return {'id':a['id']}
   if path=='/content':
    room=db.execute('SELECT * FROM rooms WHERE id=? AND user=?',(a['room'],user['id'])).fetchone()
    if not room:raise Error('room_required')
    if not a['title'].strip() or not a['details'].strip():raise Error('details_required')
    db.execute('INSERT INTO content(id,room,title,details) VALUES(?,?,?,?)',(a['id'],a['room'],a['title'],a['details']));return {'id':a['id']}
   if path=='/edit':
    self.owner(db,user,a['id'])
    if not a['title'].strip() or not a['details'].strip():raise Error('details_required')
    db.execute('UPDATE content SET title=?,details=? WHERE id=?',(a['title'],a['details'],a['id']));return {'id':a['id']}
   if path=='/complete':
    self.owner(db,user,a['id']);db.execute('UPDATE content SET complete=1 WHERE id=?',(a['id'],));return {'id':a['id']}
   if path=='/assets':
    self.owner(db,user,a['content']);kind=a['kind']
    if kind not in ['image','receipt']:raise Error('invalid_kind')
    try:
     raw=base64.b64decode(a['data'],validate=True)
     if len(raw)>5000000:raise ValueError()
     image=Image.open(BytesIO(raw));image.load();image=ImageOps.exif_transpose(image).convert('RGB');out=BytesIO();image.save(out,format='JPEG')
    except Exception:raise Error('invalid_image')
    raise Error('upload_not_implemented',501)
    db.execute('INSERT INTO assets VALUES(?,?,?,?)',(a['id'],a['content'],kind,out.getvalue()));return {'id':a['id']}
   if path=='/share':
    row=self.owner(db,user,a['id'])
    if not (user['plan'] or user['trial']):raise Error('paid_plan_required',403)
    # Downloadable share copy stays local; no public publication or email.
    return {'content':row['id'],'title':row['title'],'details':row['details']}
   raise Error('not_found',404)
 def read(self,user,path):
  with self.db() as db:
   if path=='/me':return user
   if path=='/rooms':return [dict(r) for r in db.execute('SELECT id,name FROM rooms WHERE user=? ORDER BY id',(user['id'],))]
   if path=='/content':return [dict(r) for r in db.execute('SELECT c.id,c.room,c.title,c.details,c.complete FROM content c JOIN rooms r ON r.id=c.room WHERE r.user=? ORDER BY c.id',(user['id'],))]
   if path.startswith('/assets/'):
    row=db.execute('SELECT * FROM assets WHERE id=?',(path.split('/')[-1],)).fetchone()
    if not row:raise Error('not_found',404)
    self.owner(db,user,row['content']);return row['data'],'image/jpeg'
   if path.startswith('/report/'):
    row=self.owner(db,user,path.split('/')[-1]);row['assets']=[dict(x) for x in db.execute('SELECT id,kind FROM assets WHERE content=? ORDER BY id',(row['id'],))];return row
   if path.startswith('/export/'):
    row=self.owner(db,user,path.split('/')[-1])
    if not (user['plan'] or user['trial']):raise Error('paid_plan_required',403)
    out=BytesIO();pdf=canvas.Canvas(out);pdf.setTitle('Synthetic content report');pdf.drawString(48,780,row['title']);y=744
    import textwrap
    for line in textwrap.wrap(row['details'],85):
     if y<48:pdf.showPage();y=780
     pdf.drawString(48,y,line);y-=16
    pdf.save();return out.getvalue(),'application/pdf'
   raise Error('not_found',404)
def main():
 root=Path(__file__).parent;config=json.loads(Path(os.environ['SAAS_CONFIG']).read_text());store=Store(os.environ['SAAS_DATABASE'],config)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def send(self,status,data):
   mime='application/json'
   if isinstance(data,tuple):data,mime=data
   else:data=json.dumps(data).encode()
   self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
  def execute(self):
   try:
    path=urllib.parse.urlsplit(self.path).path
    if self.command=='GET' and path in ['/','/app.js','/style.css']:
     name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path];return self.send(200,((root/name).read_bytes(),{'/':'text/html','/app.js':'text/javascript','/style.css':'text/css'}[path]))
    size=int(self.headers.get('Content-Length','0'))
    if size>7000000:raise Error('request_too_large',413)
    a=json.loads(self.rfile.read(size) or b'{}')
    if not isinstance(a,dict):raise Error('invalid_input')
    if self.command=='POST' and path in ['/register','/login']:return self.send(200,store.auth(path,a))
    token=self.headers.get('Authorization','').removeprefix('Bearer ');user=store.user(token)
    if path=='/logout' and self.command=='POST':
     with store.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
     return self.send(200,{})
    self.send(200,store.read(user,path) if self.command=='GET' else store.act(user,path,a))
   except Error as e:self.send(e.status,{'error':e.message})
   except sqlite3.IntegrityError:self.send(409,{'error':'conflict'})
   except (ValueError,KeyError,TypeError):self.send(400,{'error':'invalid_input'})
  do_GET=execute;do_POST=execute
 server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(server.server_port,flush=True);server.serve_forever()
if __name__=='__main__':main()
