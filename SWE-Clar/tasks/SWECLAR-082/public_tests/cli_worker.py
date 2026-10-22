"""Independent CLI/provider observer, candidate imported only in separate children."""
import json,subprocess,sys,tempfile,threading,os
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
r=json.load(sys.stdin);rows=[];requests=[];response=r.get('response',{})
class Provider(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(value)
  body={'source_text':value['text'],'language':value['language'],'translated_text':response.get('text','Synthetic translation')};body.update(response.get('body',{}));data=json.dumps(body).encode();self.send_response(response.get('status',200));self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=server.serve_forever,daemon=True).start();url='http://127.0.0.1:'+str(server.server_port)
try:
 with tempfile.TemporaryDirectory() as temp:
  db=Path(temp)/'state.sqlite';env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','TRANSLATION_URL':url}
  def execute(command,value):
   p=subprocess.run([sys.executable,str(Path(r['project'])/'cli.py'),'--db',str(db),command],input=json.dumps(value),capture_output=True,text=True,cwd=r['project'],env=env,timeout=90)
   return {'returncode':p.returncode,'output':json.loads(p.stdout) if p.stdout.strip() else None,'stderr':p.stderr[-800:]}
  rows.append(execute('init',r['state']))
  for op in r['operations']:rows.append(execute(op['command'],op.get('value')))
 print(json.dumps({'observations':rows,'requests':requests}))
finally:server.shutdown();server.server_close()
