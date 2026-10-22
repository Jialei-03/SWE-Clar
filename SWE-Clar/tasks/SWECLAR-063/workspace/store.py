import sqlite3,json,base64,io,math,re,hashlib
from datetime import datetime,timezone
from PIL import Image
def venue(v):
    if not isinstance(v,dict) or any(not isinstance(v.get(k),str) or not v[k].strip() for k in ['name','address']):raise ValueError('venue_required')
    for k,limit in [('latitude',90),('longitude',180)]:
        n=v.get(k)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not -limit<=n<=limit:raise ValueError('invalid_coordinate')
    return {k:v[k] for k in ['name','address','latitude','longitude']}
class Store:
    def __init__(self,path,config):
        self.path=path;self.config=config
        with self.db() as db:db.executescript('CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,owner TEXT,png BLOB);CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY,owner TEXT,image TEXT REFERENCES images(id),food TEXT,caption TEXT,venue TEXT,created TEXT);CREATE TABLE IF NOT EXISTS saves(owner TEXT,post TEXT REFERENCES posts(id),PRIMARY KEY(owner,post));')
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def actor(self,token):
        ident=self.config['tokens'].get(token)
        if ident not in self.config['users']:raise PermissionError('denied')
        return ident
    def clock(self):
        value=self.config.get('clock_file')
        d=datetime.fromisoformat(__import__('pathlib').Path(value).read_text().strip().replace('Z','+00:00')) if value else datetime.now(timezone.utc)
        if not d.tzinfo:raise ValueError('clock_timezone_required')
        return d.astimezone(timezone.utc).isoformat()
    def upload(self,user,a):raise NotImplementedError('Decode and store actual photo bytes')
    def post(self,user,a):raise NotImplementedError('Create a validated meal post')
    def visible(self,user,owner):return owner==user or owner in self.config['users'][user]['follows']
    def record(self,row,user,db):
        result={k:row[k] for k in ['id','owner','food','caption','created']};result['venue']=json.loads(row['venue']);result['image_url']='/image/'+row['image'];result['can_save']=row['owner']!=user;result['saved']=bool(db.execute('SELECT 1 FROM saves WHERE owner=? AND post=?',(user,row['id'])).fetchone());return result
    def feed(self,user):
        with self.db() as db:return [self.record(row,user,db) for row in db.execute('SELECT * FROM posts ORDER BY created DESC,id') if self.visible(user,row['owner'])]
    def save(self,user,a):
        if not isinstance(a.get('saved'),bool):raise ValueError('saved_boolean_required')
        with self.db() as db:
            row=db.execute('SELECT * FROM posts WHERE id=?',(a.get('post_id'),)).fetchone()
            if not row or row['owner']==user or not self.visible(user,row['owner']):raise PermissionError('save_denied')
            if a['saved']:db.execute('INSERT OR IGNORE INTO saves VALUES (?,?)',(user,row['id']))
            else:db.execute('DELETE FROM saves WHERE owner=? AND post=?',(user,row['id']))
            return self.record(row,user,db)
    def pins(self,user,mode):
        if mode not in ['personal','friends']:raise ValueError('map_mode')
        return [{'post_id':p['id'],'food':p['food'],**p['venue']} for p in self.feed(user) if (p['owner']==user if mode=='personal' else p['owner'] in self.config['users'][user]['follows'] and p['owner']!=user)]
    def image(self,user,ident):
        with self.db() as db:
            row=db.execute('SELECT * FROM images WHERE id=?',(ident,)).fetchone()
            if not row:raise PermissionError('image_denied')
            shared=any(self.visible(user,p['owner']) for p in db.execute('SELECT owner FROM posts WHERE image=?',(ident,)))
            if row['owner']!=user and not shared:raise PermissionError('image_denied')
            return row['png']
