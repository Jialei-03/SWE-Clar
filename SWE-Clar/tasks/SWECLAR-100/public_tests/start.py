"""Launch the web component with fresh synthetic local configuration."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import json,threading,tempfile,subprocess,sys,os
class Bridge(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));raw=json.dumps({'device_id':request.get('device_id'),'opened':request.get('operation')=='open_network_settings'}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
with tempfile.TemporaryDirectory(prefix='kiosk-demo-') as temp:
 root=Path(temp);svg=root/'art.svg';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="180"><rect width="240" height="180" fill="#d5b76d"/></svg>')
 bridge=ThreadingHTTPServer(('127.0.0.1',0),Bridge);threading.Thread(target=bridge.serve_forever,daemon=True).start()
 cfg=root/'config.json';cfg.write_text(json.dumps({'tokens':{'demo-device':{'id':'tablet-a','role':'device'},'demo-editor':{'id':'editor-a','role':'editor'},'demo-admin':{'id':'admin-a','role':'admin'}},'assets':{'art':str(svg)},'settings_url':'http://127.0.0.1:'+str(bridge.server_port)}))
 env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','KIOSK_CONFIG':str(cfg),'KIOSK_DATABASE':str(root/'catalogue.sqlite'),'PORT':os.environ.get('PORT','8188')}
 app=subprocess.Popen([sys.executable,'server.py'],env=env)
 print('Local demo: http://127.0.0.1:'+env['PORT']+'. Synthetic tokens: demo-device, demo-editor, demo-admin. Publish an invented bilingual catalogue using the documented HTTP endpoints.',flush=True)
 try:app.wait()
 except KeyboardInterrupt:app.terminate();app.wait()
 finally:bridge.shutdown();bridge.server_close()
