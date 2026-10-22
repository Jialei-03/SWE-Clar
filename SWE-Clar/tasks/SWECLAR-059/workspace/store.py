from pathlib import Path
import sqlite3,json,time,base64,io,hashlib,csv
from PIL import Image
FIELDS=['staff_id','supplier_id','name','birth_city','status','photo_id']
def text(x):return isinstance(x,str) and bool(x.strip())
class Store:
    def __init__(self,path,identities):
        self.path=path;self.identities=identities
        with self.connect() as db:db.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,supplier_id TEXT NOT NULL REFERENCES suppliers(id),data BLOB NOT NULL,digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS staff(id TEXT PRIMARY KEY,supplier_id TEXT NOT NULL REFERENCES suppliers(id),name TEXT NOT NULL,birth_city TEXT NOT NULL,status TEXT NOT NULL,photo_id TEXT REFERENCES photos(id));
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,staff_id TEXT NOT NULL,actor_id TEXT NOT NULL,old_status TEXT,new_status TEXT,timestamp INTEGER);
        CREATE TABLE IF NOT EXISTS photo_history(seq INTEGER PRIMARY KEY,staff_id TEXT NOT NULL,photo_id TEXT NOT NULL REFERENCES photos(id));
        """)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def identity(self,token):
        user=self.identities.get(token)
        if not user:raise PermissionError('unauthorized')
        return user
    def allowed(self,user,supplier):return user['role']=='review' or user.get('supplier_id')==supplier
    def require_review(self,user):
        if user['role']!='review':raise PermissionError('review_required')
    def action(self,token,action):
        user=self.identity(token);a=dict(action);kind=a.get('type')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind=='add_supplier':
                self.require_review(user);sid=a.get('supplier_id');name=a.get('name')
                if not text(sid) or not text(name):raise ValueError('invalid_supplier')
                db.execute('INSERT INTO suppliers VALUES (?,?)',(sid,name.strip()));return {'supplier_id':sid}
            if kind=='register_staff':
                sid=a.get('supplier_id')
                if not self.allowed(user,sid):raise PermissionError('supplier_denied')
                if not all(text(a.get(k)) for k in ['staff_id','supplier_id','name','birth_city']):raise ValueError('invalid_staff')
                db.execute('INSERT INTO staff VALUES (?,?,?,?,?,NULL)',(a['staff_id'],sid,a['name'].strip(),a['birth_city'].strip(),'submitted'));return {'staff_id':a['staff_id']}
            if kind in ['review','upload_photo','attach_photo','import']:raise ValueError('not_implemented')
            raise ValueError('unknown_action')
    def list_staff(self,token):
        user=self.identity(token)
        with self.connect() as db:
            rows=db.execute('SELECT id AS staff_id,supplier_id,name,birth_city,status,photo_id FROM staff ORDER BY id').fetchall()
            return [dict(row) for row in rows if self.allowed(user,row['supplier_id'])]
    def export(self,token):
        self.require_review(self.identity(token));out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader();return out.getvalue().encode()
    def photo(self,token,ident):
        user=self.identity(token)
        with self.connect() as db:
            row=db.execute('SELECT * FROM photos WHERE id=?',(ident,)).fetchone()
            if not row or not self.allowed(user,row['supplier_id']):raise PermissionError('photo_denied')
            return row['data']
    def history(self,token):
        self.require_review(self.identity(token))
        with self.connect() as db:return {'audit':[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY seq')],'photo_history':[dict(r) for r in db.execute('SELECT * FROM photo_history ORDER BY seq')]}
