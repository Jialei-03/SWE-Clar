from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from datetime import datetime,timezone
import os,json,urllib.parse,secrets,signal
from store import Store
ROOT=Path(__file__).parent;config=json.loads(Path(os.environ['STREAM_CONFIG']).read_text());store=Store(os.environ['STREAM_DATABASE'],config)
with store.db() as db:db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,viewer TEXT)')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def session(self):
        cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''));token=cookies['session'].value if 'session' in cookies else None
        with store.db() as db:
            row=db.execute('SELECT viewer FROM sessions WHERE token=?',(token,)).fetchone()
            if row:return row[0],token,False
            token=secrets.token_hex(24);viewer=secrets.token_hex(16);db.execute('INSERT INTO sessions VALUES (?,?)',(token,viewer));return viewer,token,True
    def send(self,status,data,mime='application/json',headers=None):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        url=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(url.query);files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        try:
            if url.path in files:
                name,mime=files[url.path];_,token,new=self.session();return self.send(200,(ROOT/name).read_bytes(),mime,{'Set-Cookie':f'session={token}; HttpOnly; SameSite=Strict; Path=/'} if new else {})
            if url.path=='/calendar':return self.send(200,store.calendar(params.get('now',[datetime.now(timezone.utc).isoformat()])[0]))
            if url.path=='/archives':return self.send(200,store.search(params.get('q',[''])[0],params.get('start',[None])[0],params.get('end',[None])[0]))
            if url.path.startswith('/media/'):
                event=url.path.removeprefix('/media/')
                path=store.media_path(event)
                if path is None:return self.send(404,{})
                raw=path.read_bytes();header=self.headers.get('Range')
                if header:
                    import re
                    match=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
                    if not match:return self.send(416,b'')
                    start=int(match[1]);end=int(match[2]) if match[2] else len(raw)-1
                    if start>=len(raw) or end<start:return self.send(416,b'')
                    end=min(end,len(raw)-1);return self.send(206,raw[start:end+1],'video/mp4',{'Accept-Ranges':'bytes','Content-Range':f'bytes {start}-{end}/{len(raw)}'})
                return self.send(200,raw,'video/mp4',{'Accept-Ranges':'bytes'})
            self.send(404,{})
        except Exception:self.send(400,{'error':'request_failed'})
    def do_POST(self):
        try:
            if self.path!='/view':store.admin(self.headers.get('Authorization','').removeprefix('Bearer '))
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<=20000:raise ValueError('size')
            a=json.loads(self.rfile.read(n))
            if not isinstance(a,dict):raise ValueError('body')
            if self.path=='/view':
                viewer,session,new=self.session();return self.send(200,store.view(a,viewer,session),headers={'Set-Cookie':f'session={session}; HttpOnly; SameSite=Strict; Path=/'} if new else {})
            store.admin(self.headers.get('Authorization','').removeprefix('Bearer '));methods={'/event':store.create,'/cancel':store.cancel,'/start':store.start,'/end':store.end,'/publish':store.publish}
            if self.path not in methods:return self.send(404,{})
            self.send(200,methods[self.path](a))
        except PermissionError:self.send(403,{'error':'denied'})
        except Exception:self.send(400,{'error':'request_failed'})
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler)
def stop(*a):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
print(json.dumps({'port':server.server_port}),flush=True)
try:server.serve_forever()
finally:store.media.close();server.server_close()
