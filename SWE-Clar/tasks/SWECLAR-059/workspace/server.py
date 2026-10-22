from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import json,os,sqlite3
from urllib.parse import urlsplit,parse_qs
from store import Store
ROOT=Path(__file__).parent
store=Store(os.environ['DATABASE_PATH'],json.loads(Path(os.environ['IDENTITIES_PATH']).read_text()))
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,mime,data):self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def token(self):
        header=self.headers.get('Authorization','')
        if not header.startswith('Bearer '):raise PermissionError('unauthorized')
        token=header[7:];store.identity(token);return token
    def do_GET(self):
        if self.path in ['/', '/app.js', '/style.css']:
            file,mime={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}[self.path];return self.reply(200,mime,(ROOT/file).read_bytes())
        try:
            token=self.token();url=urlsplit(self.path)
            if url.path=='/staff':return self.reply(200,'application/json',json.dumps(store.list_staff(token)).encode())
            if url.path=='/history':return self.reply(200,'application/json',json.dumps(store.history(token)).encode())
            if url.path=='/export.csv':return self.reply(200,'text/csv',store.export(token))
            if url.path=='/photo':return self.reply(200,'image/png',store.photo(token,parse_qs(url.query).get('id',[''])[0]))
            self.reply(404,'text/plain',b'Not found')
        except PermissionError:self.reply(403,'application/json',b'{"error":"forbidden"}')
        except Exception:self.reply(400,'application/json',b'{"error":"invalid_request"}')
    def do_POST(self):
        if self.path!='/action':return self.reply(404,'text/plain',b'Not found')
        try:
            token=self.token();length=int(self.headers.get('Content-Length',0))
            if not 0<length<=3000000:raise ValueError('invalid_request')
            result=store.action(token,json.loads(self.rfile.read(length)));self.reply(200,'application/json',json.dumps(result).encode())
        except PermissionError:self.reply(403,'application/json',b'{"error":"forbidden"}')
        except sqlite3.IntegrityError:self.reply(409,'application/json',b'{"error":"conflict"}')
        except Exception:self.reply(400,'application/json',b'{"error":"invalid_request"}')
http=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','0'))),Handler);print(json.dumps({'port':http.server_port}),flush=True);http.serve_forever()
