import json, sqlite3, hashlib, urllib.request, urllib.parse

class Store:
    def __init__(self,path,config):
        self.path=path;self.config=config
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS draft(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT);CREATE TABLE IF NOT EXISTS publications(version INTEGER PRIMARY KEY,change_id TEXT UNIQUE,payload TEXT);CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,device TEXT,payload TEXT);')
            db.execute('INSERT OR IGNORE INTO draft VALUES (1,?)',(json.dumps({'categories':[],'products':[]}),))
    def db(self):return sqlite3.connect(self.path,timeout=10)
    def actor(self,token):
        actor=self.config['tokens'].get(token)
        if actor is None:raise PermissionError('denied')
        return actor
    def edit(self,actor,a):raise NotImplementedError('Complete catalogue editing')
    def publish(self,actor,a):raise NotImplementedError('Publish a real content snapshot')
    def snapshot(self,actor):
        with self.db() as db:row=db.execute('SELECT payload FROM publications ORDER BY version DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else {'version':0,'categories':[],'products':[],'assets':{}}
    def track(self,actor,a):
        if actor['role']!='device':raise PermissionError('device_required')
        snap=self.snapshot(actor);kind=a.get('target_type');target=a.get('target_id');event=a.get('event_id')
        known={'page':['home'],'category':[r['id'] for r in snap['categories']],'product':[r['id'] for r in snap['products']]}
        if kind not in known or target not in known[kind] or not isinstance(event,str) or not event.strip():raise ValueError('invalid_target')
        record={'event_id':event,'target_type':kind,'target_id':target,'device_id':actor['id']}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT device,payload FROM events WHERE id=?',(event,)).fetchone()
            if old:
                if old[0]!=actor['id'] or json.loads(old[1])!=record:raise ValueError('event_conflict')
            else:db.execute('INSERT INTO events VALUES (?,?,?)',(event,actor['id'],json.dumps(record)))
        return record
    def settings(self,actor,a):
        if actor['role']!='admin':raise PermissionError('admin_required')
        device=a.get('device_id')
        if device not in [x['id'] for x in self.config['tokens'].values() if x['role']=='device']:raise ValueError('unknown_device')
        url=self.config['settings_url'];p=urllib.parse.urlsplit(url)
        if p.scheme!='http' or p.hostname not in ['127.0.0.1','localhost','::1']:raise ValueError('fixture_endpoint_required')
        body=json.dumps({'device_id':device,'operation':'open_network_settings'}).encode()
        req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as r:value=json.load(r)
        if value!={'device_id':device,'opened':True}:raise ValueError('settings_not_opened')
        return value
