"""Independent synthetic monitoring store; no production identities or device data."""
import hashlib,json,secrets,sqlite3

def connect(path):
    db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');return db

def encoded_password(value,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',value.encode(),salt.encode(),120000).hex()

def public_user(row):return {k:row[k] for k in ['id','name','role']}

def initialize(path,fixture):
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,password_hash TEXT NOT NULL,household_id TEXT);
        CREATE TABLE IF NOT EXISTS assignments(user_id TEXT,household_id TEXT,PRIMARY KEY(user_id,household_id));
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS households(id TEXT PRIMARY KEY,name TEXT,freshness_minutes REAL,night_start INTEGER,night_end INTEGER,sleep_start INTEGER,sleep_end INTEGER);
        CREATE TABLE IF NOT EXISTS rooms(household_id TEXT,id TEXT,name TEXT,PRIMARY KEY(household_id,id));
        CREATE TABLE IF NOT EXISTS sensors(household_id TEXT,id TEXT,room_id TEXT,name TEXT,kind TEXT,PRIMARY KEY(household_id,id));
        CREATE TABLE IF NOT EXISTS events(household_id TEXT,event_id TEXT,sensor_id TEXT,timestamp_ms INTEGER,value INTEGER,PRIMARY KEY(household_id,event_id));
        CREATE INDEX IF NOT EXISTS sensor_history ON events(household_id,sensor_id,timestamp_ms,event_id);
        CREATE TABLE IF NOT EXISTS rules(household_id TEXT,room_id TEXT,kind TEXT,sensor_id TEXT,enabled INTEGER,threshold_minutes REAL,severity TEXT,PRIMARY KEY(household_id,room_id,kind));
        """)
        if db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():return
        data=json.loads(fixture.read_text())
        for key in ['clock_ms','feed_token']:db.execute('INSERT INTO meta VALUES(?,?)',(key,json.dumps(data[key])))
        for r in data['households']:db.execute('INSERT INTO households VALUES(?,?,?,?,?,?,?)',tuple(r[k] for k in ['id','name','freshness_minutes','night_start','night_end','sleep_start','sleep_end']))
        for r in data['users']:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(r['id'],r['name'],r['role'],encoded_password(r['password']),r.get('household_id')))
            for home in r.get('assignments',[]):db.execute('INSERT INTO assignments VALUES(?,?)',(r['id'],home))
        for r in data['rooms']:db.execute('INSERT INTO rooms VALUES(?,?,?)',tuple(r[k] for k in ['household_id','id','name']))
        for r in data['sensors']:db.execute('INSERT INTO sensors VALUES(?,?,?,?,?)',tuple(r[k] for k in ['household_id','id','room_id','name','kind']))
        for r in data.get('events',[]):db.execute('INSERT INTO events VALUES(?,?,?,?,?)',tuple(r[k] for k in ['household_id','event_id','sensor_id','timestamp_ms','value']))
        for r in data.get('rules',[]):db.execute('INSERT INTO rules VALUES(?,?,?,?,?,?,?)',tuple(r[k] for k in ['household_id','room_id','kind','sensor_id','enabled','threshold_minutes','severity']))
        db.execute("INSERT INTO meta VALUES('initialized','true')")
