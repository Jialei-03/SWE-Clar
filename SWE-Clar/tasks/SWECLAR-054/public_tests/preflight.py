import json,sqlite3,tempfile,threading,urllib.request
from http.server import BaseHTTPRequestHandler,HTTPServer
with tempfile.TemporaryDirectory() as d:
 db=sqlite3.connect(d+'/health.db');db.execute('create table health(n integer)');db.execute('insert into health values(7)');db.commit();assert db.execute('select n from health').fetchone()==(7,);db.close()
class H(BaseHTTPRequestHandler):
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'ok')
 def log_message(self,*a):pass
s=HTTPServer(('127.0.0.1',0),H);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
assert urllib.request.urlopen('http://127.0.0.1:'+str(s.server_port),timeout=5).read()==b'ok'
s.shutdown();s.server_close();print(json.dumps({'ok':True,'sqlite':sqlite3.sqlite_version,'loopback':True}))
