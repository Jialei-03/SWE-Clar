import sqlite3,json,secrets,hashlib,re
from decimal import Decimal,ROUND_HALF_UP
class Store:
    def __init__(self,path,provider,pricing):
        self.path=path;self.provider=provider;self.pricing=pricing
        with self.connect() as db:db.executescript("""CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY);CREATE TABLE IF NOT EXISTS detections(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),payload TEXT);CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),detection_id TEXT REFERENCES detections(id),payload TEXT);CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),quote_id TEXT REFERENCES quotes(id),payload TEXT);""")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def session(self,ident):
        with self.connect() as db:
            if ident and db.execute('SELECT id FROM sessions WHERE id=?',(ident,)).fetchone():return ident,False
            ident=secrets.token_hex(24);db.execute('INSERT INTO sessions VALUES (?)',(ident,));return ident,True
    def detect(self,sid,address):
        result=self.provider.find(address);ident=secrets.token_hex(16);result['detection_id']=ident
        with self.connect() as db:db.execute('INSERT INTO detections VALUES (?,?,?)',(ident,sid,json.dumps(result)))
        return result
    def current(self,sid):
        with self.connect() as db:
            row=db.execute('SELECT * FROM detections WHERE session_id=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
            if not row:return {'detection':None,'quote':None}
            quote=db.execute('SELECT payload FROM quotes WHERE session_id=? AND detection_id=? ORDER BY rowid DESC LIMIT 1',(sid,row['id'])).fetchone();return {'detection':json.loads(row['payload']),'quote':json.loads(quote['payload']) if quote else None}
    def quote(self,sid,a):raise NotImplementedError('Calculate the estimate')
    def lead(self,sid,a):
        required=['lead_id','quote_id','name','email','phone','address']
        if any(not isinstance(a.get(k),str) or not a[k].strip() for k in required):raise ValueError('missing_contact')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',a['email'].strip()) or not re.fullmatch(r'[+()0-9 -]{5,30}',a['phone'].strip()):raise ValueError('invalid_contact')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM leads WHERE id=?',(a['lead_id'],)).fetchone()
            if old:
                if old['session_id']!=sid:raise PermissionError('lead_denied')
                return json.loads(old['payload'])
            quote=db.execute('SELECT payload FROM quotes WHERE id=? AND session_id=?',(a['quote_id'],sid)).fetchone()
            if not quote:raise PermissionError('quote_denied')
            quote=json.loads(quote['payload'])
            if a['address'].strip()!=quote['address']:raise ValueError('address_mismatch')
            result={k:a[k].strip() for k in required};result['quote']=quote;db.execute('INSERT INTO leads VALUES (?,?,?,?)',(a['lead_id'],sid,a['quote_id'],json.dumps(result)));return result
