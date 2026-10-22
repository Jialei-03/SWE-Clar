"""Provided local storage and HTTP adapter. No external service is required."""
import argparse, base64, json, re, sqlite3, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from solution import apply_delivery_event

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--data',default='runtime')
    args=parser.parse_args()
    data=Path(args.data);data.mkdir(parents=True,exist_ok=True)
    files=data/'files';files.mkdir(exist_ok=True)
    db=sqlite3.connect(data/'orders.db')
    db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    db.execute('INSERT OR IGNORE INTO orders VALUES (?,?)',('parcel-demo',json.dumps({'id':'parcel-demo','status':'created','history':[]})))
    db.commit()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,status=200,kind='application/json'):
            body=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/':return self.reply(Path(__file__).with_name('index.html').read_bytes(),kind='text/html; charset=utf-8')
            if self.path=='/api/order':
                return self.reply(json.loads(db.execute('SELECT body FROM orders WHERE id=?',('parcel-demo',)).fetchone()[0]))
            if re.fullmatch(r'/files/[0-9a-f]{32}',self.path):
                file=files/self.path.rsplit('/',1)[1]
                if file.is_file():return self.reply(file.read_bytes(),kind='application/octet-stream')
            self.reply({'error':'not_found'},404)
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=2_000_000:raise ValueError('request size')
                request=json.loads(self.rfile.read(length))
                if self.path=='/api/proofs':
                    blob=base64.b64decode(request['data'],validate=True)
                    if not blob or len(blob)>1_000_000:raise ValueError('file size')
                    token=uuid.uuid4().hex;(files/token).write_bytes(blob)
                    return self.reply({'ref':'/files/'+token},201)
                if self.path=='/api/event':
                    with db:
                        order=json.loads(db.execute('SELECT body FROM orders WHERE id=?',('parcel-demo',)).fetchone()[0])
                        result=apply_delivery_event(order,request)
                        if not isinstance(result,dict):raise ValueError('workflow result must be object')
                        if not result.get('error'):
                            db.execute('UPDATE orders SET body=? WHERE id=?',(json.dumps(result),'parcel-demo'))
                    return self.reply(result)
                self.reply({'error':'not_found'},404)
            except (ValueError,KeyError,TypeError) as error:self.reply({'error':{'code':'invalid_request','detail':str(error)}},400)
    HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__':main()
