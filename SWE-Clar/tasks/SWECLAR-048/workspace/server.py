import argparse
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from control import initial,discovery,command,ControlError
from pixels import scale,png
from wire import exchange,SourceError

ROOT=Path(__file__).resolve().parent


def load(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        row=db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None


def save(path,state):
    settings={k:state[k] for k in ('resolution','kiosk')}
    with sqlite3.connect(path) as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(settings),))


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def send(self,status,body,kind='application/json',headers=None):
        if not isinstance(body,bytes):body=json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items():self.send_header(k,str(v))
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/api/state':
            with self.server.lock:self.send(200,self.server.state)
            return
        if self.path=='/api/frame':
            try:
                with self.server.lock:state=dict(self.server.state)
                request={'op':'frame','input':state['display_input']}
                if state['display_input']=='preview':
                    if state['selected'] is None:raise ControlError('no_device')
                    request['device_id']=state['selected']
                sequence,width,height,rgb=exchange(self.server.camera_port,request)
                output_width,output_height=map(int,state['resolution'].split('x'))
                transformed=scale(rgb,width,height,output_width,output_height,state['zoom'])
                self.send(200,png(transformed,output_width,output_height),'image/png',{'X-Frame-Sequence':sequence,'X-Display-Input':state['display_input']})
            except SourceError as error:self.send(502,{'error':str(error)})
            except ControlError as error:self.send(409,{'error':str(error)})
            return
        files={'/':('index.html','text/html; charset=utf-8'),'/viewer.js':('viewer.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path not in files:return self.send(404,{'error':'not_found'})
        name,kind=files[self.path];self.send(200,(ROOT/name).read_bytes(),kind)
    def do_POST(self):
        if self.path not in ('/api/scan','/api/control'):return self.send(404,{'error':'not_found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096:raise ControlError('invalid_event')
            event=json.loads(self.rfile.read(length))
            with self.server.lock:
                if self.path=='/api/scan':
                    if event!={}:raise ControlError('invalid_event')
                    after=discovery(self.server.state,exchange(self.server.camera_port,{'op':'list'}))
                else:after=command(self.server.state,event)
                save(self.server.db,after);self.server.state=after
                self.send(200,after)
        except SourceError as error:self.send(502,{'error':str(error)})
        except (ValueError,TypeError,KeyError) as error:self.send(400,{'error':str(error) if isinstance(error,ControlError) else 'invalid_event'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--db',default='camera.sqlite');parser.add_argument('--camera-port',type=int)
    args=parser.parse_args();source=None
    if not args.camera_port:
        from synthetic_source import Source
        source=Source();args.camera_port=source.start()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.db=args.db;server.camera_port=args.camera_port;server.lock=threading.RLock()
    server.state=initial(load(args.db))
    try:server.state=discovery(server.state,exchange(args.camera_port,{'op':'list'}))
    except SourceError:pass
    print(json.dumps({'port':server.server_port}),flush=True)
    try:server.serve_forever()
    finally:
        server.server_close()
        if source:source.stop()
