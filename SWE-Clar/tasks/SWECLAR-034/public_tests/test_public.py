"""Visible starter regression: real HTTP, synthetic fixtures and empty CLI input."""
import json,os,subprocess,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
if os.geteuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
sys.path.insert(0,str(root))
from fetcher import fetch_html
pages={name:(root/'examples'/name).read_text() for name in ['detail.html','compact.html']}
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  body=pages.get(self.path.lstrip('/'))
  if body is None:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body.encode('utf8'))
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 for name,body in pages.items():assert fetch_html(f'http://127.0.0.1:{server.server_port}/{name}')==body
finally:server.shutdown();server.server_close();thread.join()
result=subprocess.run([sys.executable,str(root/'solution.py')],input='[]',capture_output=True,text=True,cwd=root,timeout=5)
assert result.returncode==0,result.stderr
assert json.loads(result.stdout)==[]
print(json.dumps({'passed':True,'checks':['two synthetic layouts fetched over HTTP','empty-input command-line round trip']}))
