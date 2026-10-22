"""Provided JSON console and ephemeral synthetic HTTP source."""
import argparse,json,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from solution import process_trend_action

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sample-source',action='store_true');args=parser.parse_args()
    request=json.load(sys.stdin);state=request['state'];action=dict(request['action'])
    server=None;thread=None
    try:
        if args.sample_source:
            csv=(Path(__file__).with_name('example.csv')).read_bytes()
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path!='/measurements.csv':self.send_error(404);return
                    self.send_response(200);self.send_header('Content-Type','text/csv');self.send_header('Content-Length',str(len(csv)));self.end_headers();self.wfile.write(csv)
                def log_message(self,*args):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            action['url']=f'http://127.0.0.1:{server.server_port}/measurements.csv'
        result=process_trend_action(state,action)
        print(json.dumps(result,allow_nan=False))
    finally:
        if server:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()
