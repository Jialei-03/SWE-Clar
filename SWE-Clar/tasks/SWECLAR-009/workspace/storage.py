"""Independent synthetic hiring store, including actual resume bytes."""
import base64,hashlib,json,secrets,sqlite3

def connect(path):
 db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db

def password_hash(value,salt=None):
 salt=salt or secrets.token_hex(16);return salt+'$'+hashlib.pbkdf2_hmac('sha256',value.encode(),salt.encode(),120000).hex()

def public_user(row):return {key:row[key] for key in ['id','name','role','bio']}

def initialize(path,fixture):
 with connect(path) as db:
  db.execute('PRAGMA journal_mode=WAL')
  db.executescript("""
  CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT,role TEXT,bio TEXT,password_hash TEXT);
  CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id));
  CREATE TABLE IF NOT EXISTS relationships(actor_id TEXT REFERENCES users(id),target_id TEXT REFERENCES users(id),kind TEXT,PRIMARY KEY(actor_id,target_id,kind));
  CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,employer_id TEXT REFERENCES users(id),title TEXT,description TEXT,category TEXT,location TEXT,active INTEGER);
  CREATE TABLE IF NOT EXISTS bookmarks(employee_id TEXT REFERENCES users(id),job_id TEXT REFERENCES jobs(job_id),PRIMARY KEY(employee_id,job_id));
  CREATE TABLE IF NOT EXISTS resumes(resume_id TEXT PRIMARY KEY,owner_id TEXT REFERENCES users(id),filename TEXT,content BLOB,size_bytes INTEGER,sha256 TEXT);
  CREATE TABLE IF NOT EXISTS applications(application_id TEXT PRIMARY KEY,job_id TEXT REFERENCES jobs(job_id),employee_id TEXT REFERENCES users(id),resume_id TEXT REFERENCES resumes(resume_id),status TEXT,UNIQUE(job_id,employee_id));
  CREATE TABLE IF NOT EXISTS interviews(interview_id TEXT PRIMARY KEY,application_id TEXT UNIQUE REFERENCES applications(application_id),start_ms INTEGER,end_ms INTEGER);
  CREATE TABLE IF NOT EXISTS views(viewer_id TEXT REFERENCES users(id),event_id TEXT,job_id TEXT REFERENCES jobs(job_id),timestamp_ms INTEGER,PRIMARY KEY(viewer_id,event_id));
  """)
  if db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():return
  data=json.loads(fixture.read_text());db.execute('INSERT INTO meta VALUES(?,?)',('clock_ms',json.dumps(data['clock_ms'])))
  for r in data['users']:db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(r['id'],r['name'],r['role'],r['bio'],password_hash(r['password'])))
  for r in data.get('jobs',[]):db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',tuple(r[k] for k in ['job_id','employer_id','title','description','category','location','active']))
  for r in data.get('relationships',[]):db.execute('INSERT INTO relationships VALUES(?,?,?)',tuple(r[k] for k in ['actor_id','target_id','kind']))
  for r in data.get('resumes',[]):
   content=base64.b64decode(r['content_base64']);db.execute('INSERT INTO resumes VALUES(?,?,?,?,?,?)',(r['resume_id'],r['owner_id'],r['filename'],content,len(content),hashlib.sha256(content).hexdigest()))
  for r in data.get('applications',[]):db.execute('INSERT INTO applications VALUES(?,?,?,?,?)',tuple(r[k] for k in ['application_id','job_id','employee_id','resume_id','status']))
  for r in data.get('interviews',[]):db.execute('INSERT INTO interviews VALUES(?,?,?,?)',tuple(r[k] for k in ['interview_id','application_id','start_ms','end_ms']))
  for r in data.get('views',[]):db.execute('INSERT INTO views VALUES(?,?,?,?)',tuple(r[k] for k in ['viewer_id','event_id','job_id','timestamp_ms']))
  db.execute("INSERT INTO meta VALUES('initialized','true')")
