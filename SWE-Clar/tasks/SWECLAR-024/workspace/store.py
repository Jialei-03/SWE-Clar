import json,sqlite3,re,hashlib,threading
from datetime import datetime,timezone
from pathlib import Path
from media import Media
def instant(value):
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('timezone_required')
    return d.astimezone(timezone.utc).isoformat(timespec='microseconds')
class Store:
    def __init__(self,path,config):
        self.path=path;self.config=config;self.media=Media(config['media_root']);self.lock=threading.RLock()
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,title TEXT,start TEXT,end TEXT,status TEXT);CREATE TABLE IF NOT EXISTS archives(event TEXT PRIMARY KEY REFERENCES events(id),payload TEXT,published INTEGER,terms TEXT);CREATE TABLE IF NOT EXISTS views(event TEXT REFERENCES archives(event),viewer TEXT,session TEXT,PRIMARY KEY(event,viewer,session));')
            db.execute("UPDATE events SET status='interrupted' WHERE status='live'")
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.execute('PRAGMA foreign_keys=ON');return db
    def admin(self,token):
        if token!=self.config['admin_token']:raise PermissionError('admin_required')
    def create(self,a):
        ident=a.get('event_id');title=a.get('title');start=instant(a['start']);end=instant(a['end'])
        if not isinstance(ident,str) or not re.fullmatch('[a-z0-9_-]{1,60}',ident) or not isinstance(title,str) or not title.strip() or end<=start:raise ValueError('invalid_event')
        if ident not in self.config['stream_keys']:raise ValueError('unconfigured_event')
        with self.db() as db:db.execute('INSERT INTO events VALUES (?,?,?,?,?)',(ident,title.strip(),start,end,'scheduled'))
        return {'event_id':ident}
    def calendar(self,now):
        now=instant(now)
        with self.db() as db:rows=db.execute("SELECT id,title,start,end FROM events WHERE status='scheduled' AND start>=? ORDER BY start,id",(now,)).fetchall()
        return [dict(zip(['event_id','title','start','end'],r)) for r in rows]
    def cancel(self,a):
        with self.lock,self.db() as db:
            row=db.execute('SELECT status FROM events WHERE id=?',(a['event_id'],)).fetchone()
            if not row or row[0]!='scheduled':raise ValueError('not_scheduled')
            db.execute("UPDATE events SET status='cancelled' WHERE id=?",(a['event_id'],))
        return {'cancelled':True}
    def start(self,a):
        event=a['event_id']
        with self.lock,self.db() as db:
            row=db.execute('SELECT status FROM events WHERE id=?',(event,)).fetchone()
            if not row or row[0]!='scheduled' or a.get('stream_key')!=self.config['stream_keys'].get(event):raise ValueError('start_denied')
            result=self.media.begin(event,a['stream_key']);db.execute("UPDATE events SET status='live' WHERE id=?",(event,));return result
    def end(self,a):
        event=a['event_id']
        with self.lock,self.db() as db:
            row=db.execute('SELECT status FROM events WHERE id=?',(event,)).fetchone()
            if not row or row[0]!='live':raise ValueError('not_live')
            try:info=self.media.end(event)
            except Exception:db.execute("UPDATE events SET status='interrupted' WHERE id=?",(event,));db.commit();raise
            db.execute('INSERT INTO archives VALUES (?,?,0,?)',(event,json.dumps(info),'[]'));db.execute("UPDATE events SET status='ended' WHERE id=?",(event,));return {k:v for k,v in info.items() if k!='path'}
    def publish(self,a):
        raise NotImplementedError('Complete archive validation and publication')
    def media_path(self,event):
        with self.db() as db:row=db.execute('SELECT payload FROM archives WHERE event=? AND published=1',(event,)).fetchone()
        if not row:return None
        path=Path(json.loads(row[0])['path'])
        return path if path.is_file() else None
    def search(self,query='',start=None,end=None):
        start=instant(start) if start else None;end=instant(end) if end else None
        with self.db() as db:rows=db.execute('SELECT e.id,e.title,e.start,a.terms,a.payload FROM events e JOIN archives a ON e.id=a.event WHERE a.published=1 ORDER BY e.start,e.id').fetchall()
        return [{'event_id':r[0],'title':r[1],'start':r[2],'media_url':'/media/'+r[0],'duration':json.loads(r[4])['duration']} for r in rows if (not query or query.casefold() in (r[1]+' '+' '.join(json.loads(r[3]))).casefold()) and (not start or r[2]>=start) and (not end or r[2]<end)]
    def view(self,a,viewer,session):
        raise NotImplementedError('Complete playback counting')
