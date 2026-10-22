"""Protected synthetic receipt adapter, independently inspectable over HTTP."""
import argparse,json,re,socket,sqlite3,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlsplit


class Adapter:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'adapter.sqlite3',isolation_level=None,check_same_thread=False)
        self.lock=threading.RLock()
        self.db.executescript('CREATE TABLE IF NOT EXISTS receipts(target TEXT,request_id TEXT,envelope TEXT,PRIMARY KEY(target,request_id)); CREATE TABLE IF NOT EXISTS requests(method TEXT,path TEXT,header TEXT,envelope TEXT);')
    def handle(self,method,path,header,value):
        with self.lock:
            self.db.execute('INSERT INTO requests VALUES(?,?,?,?)',(method,path,header,json.dumps(value,ensure_ascii=True)))
            if method=='GET' and path=='/health':return 200,{'ok':True},False
            match=re.fullmatch('/(deliveries|receipts)/(table|mail|archive)',path)
            if not match:return 404,{'error':{'code':'not_found'}},False
            kind,target=match.groups()
            if method=='GET' and kind=='receipts':
                return 200,{'receipts':[json.loads(row[0]) for row in self.db.execute('SELECT envelope FROM receipts WHERE target=? ORDER BY rowid',(target,))]},False
            if method!='POST' or kind!='deliveries':return 404,{'error':{'code':'not_found'}},False
            try:
                if re.search(r'%(?![0-9a-fA-F]{2})',header):raise ValueError()
                key=unquote(header,encoding='utf-8',errors='strict')
                assert isinstance(value,dict) and isinstance(value.get('request_id'),str) and 1<=len(value['request_id'])<=100
                assert value['request_id']==key and value.get('target')==target and isinstance(value.get('report'),dict)
                assert not any(0xD800<=ord(c)<=0xDFFF for c in key)
            except (ValueError,AssertionError):return 400,{'error':{'code':'invalid_request'}},False
            settings=self.root/'controls.json';mode=json.loads(settings.read_text()).get('mode','normal') if settings.exists() else 'normal'
            if mode=='unavailable':return 503,{'accepted':False},False
            row=self.db.execute('SELECT envelope FROM receipts WHERE target=? AND request_id=?',(target,key)).fetchone()
            if row and json.loads(row[0])!=value:return 409,{'accepted':False,'error':{'code':'conflict'}},False
            if not row:self.db.execute('INSERT INTO receipts VALUES(?,?,?)',(target,key,json.dumps(value,ensure_ascii=True)))
            response={'accepted':True,'request_id':key,'target':target}
            if mode=='bad_ack':response['request_id']='incorrect-synthetic-ack'
            if mode=='accepted_false':response['accepted']=False
            return 200 if row else 201,response,mode=='lose_response'


class Handler(BaseHTTPRequestHandler):
    def dispatch(self):
        try:
            body=None
            if self.command=='POST':
                n=int(self.headers.get('Content-Length','0'))
                if not 1<=n<=1048576 or self.headers.get('Transfer-Encoding'):raise ValueError()
                raw=self.rfile.read(n)
                if len(raw)!=n:raise ValueError()
                body=json.loads(raw.decode(),parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            status,value,lose=self.server.adapter.handle(self.command,urlsplit(self.path).path,self.headers.get('Idempotency-Key',''),body)
        except (ValueError,UnicodeError):status,value,lose=400,{'error':{'code':'invalid_request'}},False
        if lose:
            self.close_connection=True
            try:self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            return
        raw=json.dumps(value,ensure_ascii=True).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    do_GET=do_POST=dispatch
    def log_message(self,*_):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);parser.add_argument('--port',type=int,default=8081);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.adapter=Adapter(args.state)
    print(json.dumps({'port':server.server_port}),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
