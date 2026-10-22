from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()));from fetcher import fetch_text
from http.server import HTTPServer,BaseHTTPRequestHandler
from threading import Thread
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'<html>synthetic archive</html>')
 def log_message(self,*args):pass
s=HTTPServer(('127.0.0.1',0),Handler);t=Thread(target=s.serve_forever,daemon=True);t.start()
try:assert fetch_text('http://127.0.0.1:'+str(s.server_port))=='<html>synthetic archive</html>'
finally:s.shutdown();s.server_close();t.join()
print('Public HTML transport passed')
