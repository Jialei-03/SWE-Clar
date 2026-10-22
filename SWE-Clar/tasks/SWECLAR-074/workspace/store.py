import json,sqlite3,hashlib,secrets,hmac,math
from datetime import datetime,timezone
def instant(value):
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('timezone_required')
    return d.astimezone(timezone.utc)
def point(row):
    for key,bound in [('latitude',90),('longitude',180)]:
        value=row.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not -bound<=value<=bound:raise ValueError('invalid_point')
    return {key:row[key] for key in ['latitude','longitude']}
class Store:
    def __init__(self,path,config):
        self.path=path;self.config=config
        with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT)')
    def db(self):return sqlite3.connect(self.path,timeout=10)
    def login(self,a):raise NotImplementedError('Authenticate using the local credential record')
    def actor(self,token):
        with self.db() as db:row=db.execute('SELECT user FROM sessions WHERE hash=?',(hashlib.sha256((token or '').encode()).hexdigest(),)).fetchone()
        if not row or row[0] not in self.config['users']:raise PermissionError('login_required')
        return {'username':row[0],'name':self.config['users'][row[0]]['name']}
    def logout(self,token):
        with self.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256((token or '').encode()).hexdigest(),))
    def locations(self,query):return [{'id':row['id'],'name':row['name'],**point(row)} for row in self.config['locations'] if query.casefold() in row['name'].casefold()]
    def tracks(self):return [{'id':t['id'],'name':t['name'],'description':t['description']} for t in self.config['tracks']]
    def rewind(self,ident,at):raise NotImplementedError('Select the historical sample')
