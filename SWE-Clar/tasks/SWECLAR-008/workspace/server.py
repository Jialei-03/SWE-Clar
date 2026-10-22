"""Local HTTP monitoring application using only independently authored fixtures."""
import argparse,csv,hmac,io,json,re,secrets,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import monitoring
from storage import connect,initialize,encoded_password,public_user

class Problem(Exception):
    def __init__(self,status,code):self.status=status;self.code=code

def require(test,code='invalid',status=400):
    if not test:raise Problem(status,code)

def identifier(value):return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value) is not None

def fields(body,names):require(isinstance(body,dict) and set(body)==set(names))

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,payload,kind='application/json',filename=None):
        raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else payload
        self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):self.handle_request()
    def do_POST(self):self.handle_request()
    def do_PUT(self):self.handle_request()
    def handle_request(self):
        try:
            route=urlparse(self.path)
            static={'/':('index.html','text/html'),'/ui.js':('ui.js','text/javascript'),'/style.css':('style.css','text/css')}
            if self.command=='GET' and route.path in static:
                name,kind=static[route.path];self.send(200,(Path(__file__).parent/'web'/name).read_bytes(),kind);return
            if self.command=='GET' and route.path=='/health':self.send(200,{'ok':True});return
            body={}
            if self.command in ['POST','PUT']:
                size=int(self.headers.get('Content-Length','0'));require(0<size<=65536)
                body=json.loads(self.rfile.read(size),parse_constant=lambda _:None);require(isinstance(body,dict))
            with connect(self.server.db) as db:
                db.execute('BEGIN IMMEDIATE')
                data=self.dispatch(db,route,body)
            if route.path=='/api/report.csv':self.send(200,data,'text/csv','activity-report.csv')
            else:self.send(200,data)
        except Problem as error:self.send(error.status,{'error':{'code':error.code}})
        except (ValueError,UnicodeError,TypeError):self.send(400,{'error':{'code':'invalid'}})
        except sqlite3.Error:self.send(503,{'error':{'code':'storage_unavailable'}})
    def actor(self,db):
        auth=self.headers.get('Authorization','');require(auth.startswith('Bearer '),'unauthorized',401)
        user=db.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=?',(auth[7:],)).fetchone();require(user is not None,'unauthorized',401);return user
    def query(self,route):
        values=parse_qs(route.query,keep_blank_values=True);require(all(len(v)==1 for v in values.values()));return {k:v[0] for k,v in values.items()}
    def authorized_home(self,db,user,ident):
        require(identifier(ident));require(ident in monitoring.homes(db,user),'denied',403)
        home=db.execute('SELECT * FROM households WHERE id=?',(ident,)).fetchone();require(home is not None,'denied',403);return home
    def dispatch(self,db,route,body):
        path=route.path;method=self.command
        if method=='POST' and path=='/api/login':
            fields(body,['id','password']);require(isinstance(body['id'],str) and isinstance(body['password'],str))
            user=db.execute('SELECT * FROM users WHERE id=?',(body['id'],)).fetchone()
            require(user is not None and hmac.compare_digest(user['password_hash'],encoded_password(body['password'],user['password_hash'].split('$')[0])),'unauthorized',401)
            token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(token,user['id']));return {'token':token,'user':public_user(user)}
        if method=='POST' and path=='/api/ingest':
            secret=json.loads(db.execute("SELECT value FROM meta WHERE key='feed_token'").fetchone()[0]);require(hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+secret),'unauthorized',401)
            fields(body,['household_id','event_id','sensor_id','timestamp_ms','value'])
            require(all(identifier(body[k]) for k in ['household_id','event_id','sensor_id']) and type(body['timestamp_ms']) is int and 0<=body['timestamp_ms']<=253402300799999 and type(body['value']) is bool)
            require(db.execute('SELECT 1 FROM sensors WHERE household_id=? AND id=?',(body['household_id'],body['sensor_id'])).fetchone() is not None,'not_found',404)
            existing=db.execute('SELECT * FROM events WHERE household_id=? AND event_id=?',(body['household_id'],body['event_id'])).fetchone()
            if existing:
                require(all(existing[k]==body[k] for k in ['sensor_id','timestamp_ms','value']),'event_conflict',409);return {'accepted':True,'duplicate':True}
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',tuple(body[k] for k in ['household_id','event_id','sensor_id','timestamp_ms','value']));return {'accepted':True,'duplicate':False}
        user=self.actor(db)
        if method=='POST' and path=='/api/logout':
            fields(body,[]);db.execute('DELETE FROM sessions WHERE token=?',(self.headers['Authorization'][7:],));return {'ok':True}
        if method=='GET' and path=='/api/me':return {'user':public_user(user)}
        if method=='GET' and path=='/api/homes':
            allowed=monitoring.homes(db,user);return {'households':[dict(db.execute('SELECT * FROM households WHERE id=?',(ident,)).fetchone()) for ident in sorted(allowed)],'clock_ms':json.loads(db.execute("SELECT value FROM meta WHERE key='clock_ms'").fetchone()[0])}
        if method=='PUT' and path=='/api/rules':
            fields(body,['household_id','room_id','kind','sensor_id','enabled','threshold_minutes','severity'])
            self.authorized_home(db,user,body['household_id'])
            status,data=monitoring.save_rule(db,user,body)
            if status!=200:raise Problem(status,data)
            return {'rule':data}
        query=self.query(route);home=self.authorized_home(db,user,query.get('household_id'))
        if method=='GET' and path=='/api/rules':
            require(set(query)=={'household_id','room_id'});room=query['room_id'];require(identifier(room));require(db.execute('SELECT 1 FROM rooms WHERE household_id=? AND id=?',(home['id'],room)).fetchone() is not None,'not_found',404)
            return {'rules':monitoring.saved_rules(db,home['id'],room)}
        require(set(query)=={'household_id','as_of'});require(re.fullmatch(r'[0-9]+',query['as_of']) is not None);as_of=int(query['as_of']);require(0<=as_of<=253402300799999)
        if method=='GET' and path=='/api/snapshot':return {'as_of':as_of,'rooms':monitoring.snapshot(db,home,as_of)}
        if method=='GET' and path=='/api/alerts':return {'as_of':as_of,'alerts':monitoring.alerts(db,home,as_of)}
        if method=='GET' and path in ['/api/report','/api/report.csv']:
            result=monitoring.report(db,home,as_of)
            if path.endswith('.csv'):
                out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=['household_id','room_id','event_count','sleep_event_count','alert_count']);writer.writeheader()
                for row in result['rooms']:writer.writerow({k:row[k] for k in writer.fieldnames})
                return out.getvalue().encode()
            return result
        raise Problem(404,'not_found')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--db',type=Path,required=True);parser.add_argument('--fixtures',type=Path,default=Path('fixtures/demo.json'));args=parser.parse_args()
    initialize(args.db,args.fixtures);server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True;server.db=args.db
    print(json.dumps({'port':server.server_port}),flush=True)
    try:server.serve_forever()
    finally:server.server_close()
if __name__=='__main__':main()
