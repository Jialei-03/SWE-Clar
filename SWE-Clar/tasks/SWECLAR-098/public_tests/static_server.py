from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import os,json
ROOT=Path.cwd().resolve()
class H(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if not Path(self.translate_path(self.path)).resolve().is_relative_to(ROOT):self.send_error(404);return
  super().do_GET()
s=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT',0))),H);print(json.dumps({'port':s.server_port}),flush=True);s.serve_forever()
