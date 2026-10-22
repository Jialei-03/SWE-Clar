import argparse,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from solution import process_mentor_event

def serve(database_path,port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/health':self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
            else:self.send_response(404);self.end_headers()
        def do_POST(self):
            if self.path!='/events':self.send_response(404);self.end_headers();return
            try:
                event=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                if not isinstance(event,dict):raise ValueError('object required')
                result=process_mentor_event(database_path,event)
            except (ValueError,TypeError):result={'error':{'code':'invalid_event'}}
            self.send_response(400 if 'error' in result else 200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(result).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',required=True);parser.add_argument('--port',type=int,default=8080);args=parser.parse_args();serve(args.db,args.port)
