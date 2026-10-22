"""Independently authored HTTP/SQLite service for synthetic practice records."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import quote, unquote, urlsplit
from urllib.error import HTTPError, URLError
import hashlib,hmac,json,math,os,re,secrets,sqlite3

class Error(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status

def fields(data,expected):
    if not isinstance(data,dict) or set(data)!=set(expected):raise Error('invalid_fields')

def text(value,maximum,trim=False):
    if not isinstance(value,str):raise Error('invalid_text')
    value=value.strip() if trim else value
    if not 1<=len(value)<=maximum:raise Error('invalid_text')
    return value

def goal_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):raise Error('invalid_goal_id')
    return value

class Store:
    def __init__(self,path,config):
        self.path=path;self.config=config
        if len(config['questions'])!=6 or len({q['id'] for q in config['questions']})!=6:raise ValueError('Six unique questions required')
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,login TEXT UNIQUE,salt TEXT,verifier TEXT);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(transaction_id TEXT PRIMARY KEY,user TEXT,product TEXT,store TEXT);
CREATE TABLE IF NOT EXISTS goals(id TEXT,user TEXT,title TEXT,complete INTEGER DEFAULT 0,PRIMARY KEY(user,id));
CREATE TABLE IF NOT EXISTS surveys(id INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT,answers TEXT);''')
            initial_users=config['users'] if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone() else []
            for user in initial_users:
                if db.execute('SELECT 1 FROM users WHERE id=?',(user['id'],)).fetchone():continue
                salt=secrets.token_hex(16)
                db.execute('INSERT INTO users VALUES(?,?,?,?)',(user['id'],user['login'],salt,self.digest(user['password'],salt)))
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;return db
    def digest(self,password,salt):
        return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    def login(self,data):
        fields(data,['login','password']);login=text(data['login'],128);password=text(data['password'],256)
        with self.db() as db:
            row=db.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
            if not row or not hmac.compare_digest(row['verifier'],self.digest(password,row['salt'])):raise Error('invalid_login',401)
            token=secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id']))
        return {'token':token}
    def actor(self,token):
        with self.db() as db:row=db.execute('SELECT user FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:raise Error('unauthorized',401)
        return row['user']
    def logout(self,token):
        with self.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        return {}
    def activate(self,user,data):
        raise Error('activation_pending',501)
    def act(self,user,path,data):
        if path=='/activate':return self.activate(user,data)
        with self.db() as db:
            if path=='/goals':
                fields(data,['id','title']);key=goal_id(data['id']);title=text(data['title'],120,trim=True)
                db.execute('INSERT INTO goals(id,user,title) VALUES(?,?,?)',(key,user,title));return {'id':key}
            if path=='/complete-goal':
                fields(data,['id']);key=goal_id(data['id'])
                if not db.execute('SELECT 1 FROM goals WHERE user=? AND id=?',(user,key)).fetchone():raise Error('not_found',404)
                if not db.execute('SELECT 1 FROM surveys WHERE user=?',(user,)).fetchone():raise Error('survey_required')
                db.execute('UPDATE goals SET complete=1 WHERE user=? AND id=?',(user,key));return {'id':key,'complete':True}
            if path=='/surveys':
                fields(data,['answers']);answers=data['answers'];keys={q['id'] for q in self.config['questions']}
                if not isinstance(answers,dict) or set(answers)!=keys:raise Error('invalid_answers')
                if any(type(v) not in (int,float) or not 0<=v<=10 or not math.isfinite(v) for v in answers.values()):raise Error('invalid_answers')
                row=db.execute('INSERT INTO surveys(user,answers) VALUES(?,?)',(user,json.dumps(answers,allow_nan=False)))
                return {'id':row.lastrowid}
        raise Error('not_found',404)
    def read(self,user,path):
        with self.db() as db:
            if path=='/me':return {'id':user}
            if path=='/products':return self.config['products']
            if path=='/questions':return self.config['questions']
            if path=='/tracks':return [{k:v for k,v in t.items() if k!='filename'} for t in self.config['tracks'] if t['playlists']]
            if path=='/goals':return [dict(row) for row in db.execute('SELECT id,title,complete FROM goals WHERE user=? ORDER BY id',(user,))]
            if path=='/subscriptions':return [dict(row) for row in db.execute('SELECT transaction_id,product,store FROM subscriptions WHERE user=? ORDER BY transaction_id',(user,))]
            if path=='/report':
                rows=[json.loads(row[0]) for row in db.execute('SELECT answers FROM surveys WHERE user=? ORDER BY id',(user,))]
                return {'count':len(rows),'latest':rows[-1] if rows else {},'overall':{q['id']:rows[-1][q['id']] for q in self.config['questions']} if rows else {}}
        raise Error('not_found',404)

def main():
    root=Path(__file__).parent;config=json.loads(Path(os.environ['PRACTICE_CONFIG']).read_text());store=Store(os.environ['PRACTICE_DATABASE'],config);assets=Path(os.environ['PRACTICE_ASSETS']).resolve()
    gets={'/me','/products','/tracks','/questions','/goals','/report','/subscriptions'}
    posts={'/login','/activate','/goals','/complete-goal','/surveys','/logout'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def send(self,status,data,mime='application/json',headers=None):
            raw=json.dumps(data,allow_nan=False).encode() if mime=='application/json' else data
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def execute(self):
            try:
                path=urlsplit(self.path).path;audio=path.startswith('/audio/')
                if self.command=='GET' and path in ['/','/app.js']:
                    name='index.html' if path=='/' else 'app.js'
                    return self.send(200,(root/'dist'/name).read_bytes(),'text/html' if path=='/' else 'text/javascript')
                if path not in gets|posts and not audio:raise Error('not_found',404)
                if (self.command=='GET' and path not in gets and not audio) or (self.command=='POST' and path not in posts):raise Error('method_not_allowed',405)
                size=int(self.headers.get('Content-Length','0'))
                if not 0<=size<=65536:raise Error('request_too_large',413)
                data=json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data,dict):raise Error('invalid_input')
                if path=='/login':return self.send(200,store.login(data))
                header=self.headers.get('Authorization','')
                if not header.startswith('Bearer '):raise Error('unauthorized',401)
                token=header[7:];user=store.actor(token)
                if path=='/logout':fields(data,[]);return self.send(200,store.logout(token))
                if audio:
                    ident=unquote(path[len('/audio/'):]);track=next((t for t in config['tracks'] if t['id']==ident and t['playlists']),None)
                    if not track:raise Error('not_found',404)
                    file=(assets/track['filename']).resolve()
                    if not file.is_relative_to(assets) or not file.is_file():raise Error('not_found',404)
                    raw=file.read_bytes();requested=self.headers.get('Range');headers={'Accept-Ranges':'bytes'}
                    if requested:
                        match=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
                        if not match:raise Error('invalid_range',416)
                        start=int(match[1]);end=min(len(raw)-1,int(match[2])) if match[2] else len(raw)-1
                        if start>end or start>=len(raw):raise Error('invalid_range',416)
                        headers['Content-Range']=f'bytes {start}-{end}/{len(raw)}'
                        return self.send(206,raw[start:end+1],'audio/wav',headers)
                    return self.send(200,raw,'audio/wav',headers)
                return self.send(200,store.read(user,path) if self.command=='GET' else store.act(user,path,data))
            except Error as exc:self.send(exc.status,{'error':exc.message})
            except sqlite3.IntegrityError:self.send(409,{'error':'conflict'})
            except (ValueError,TypeError,KeyError,UnicodeError):self.send(400,{'error':'invalid_input'})
            except FileNotFoundError:self.send(404,{'error':'not_found'})
        def unsupported(self):self.send(405,{'error':'method_not_allowed'})
        do_GET=execute;do_POST=execute
        do_PUT=unsupported;do_PATCH=unsupported;do_DELETE=unsupported;do_HEAD=unsupported;do_OPTIONS=unsupported
    server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler)
    print(server.server_port,flush=True);server.serve_forever()

if __name__=='__main__':main()
