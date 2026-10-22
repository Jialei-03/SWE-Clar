"""Public regression smoke: source registration and actual HTTP reading."""
import copy,importlib.util,json,os,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
if os.geteuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
sys.path.insert(0,str(root))
from solution import process_exhibition_action
from fetcher import fetch_text
state={'sources':{},'exhibitions':{}}
action={'type':'add_source','source':{'source_id':'sample','museum':'Example Gallery','city':'Example City','url':'http://127.0.0.1/feeds/sample','feed_type':'JSON'}}
before=copy.deepcopy((state,action));result=process_exhibition_action(state,action)
assert (state,action)==before
assert all(result['sources']['sample'].get(k)==v for k,v in action['source'].items())
body=(root/'example.json').read_text();json.loads(body)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(body.encode('utf8'))
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:assert fetch_text(f'http://127.0.0.1:{server.server_port}/sample')==body
finally:server.shutdown();server.server_close();thread.join()
print(json.dumps({'passed':True,'checks':['source registration','input preservation','real local HTTP reader','synthetic example format']}))
