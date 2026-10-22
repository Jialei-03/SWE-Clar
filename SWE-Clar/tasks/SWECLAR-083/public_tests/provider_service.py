import json,sys
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
def network():return {'nodes':{'s':{'lat':0,'lon':0},'a':{'lat':0,'lon':0.01},'b':{'lat':0.01,'lon':0.01},'c':{'lat':0.01,'lon':0},'d':{'lat':0,'lon':-0.011},'e':{'lat':0.009,'lon':-0.011},'f':{'lat':0.009,'lon':0},'g':{'lat':0,'lon':0.02},'h':{'lat':0.02,'lon':0.02},'i':{'lat':0.02,'lon':0}},'edges':[['s','a'],['a','b'],['b','c'],['c','s'],['s','d'],['d','e'],['e','f'],['f','s'],['s','g'],['g','h'],['h','i'],['i','s']]}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))));raw=json.dumps(network()).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
