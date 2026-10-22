"""Candidate-independent capability check before the coding budget."""
import json,threading,urllib.request,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'[{"synthetic":true}]')
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{server.server_port}/health',timeout=3) as response:assert json.load(response)==[{'synthetic':True}]
 assert ET.fromstring('<rss><channel/></rss>').find('channel') is not None
 HTMLParser().feed('<article>synthetic</article>')
finally:server.shutdown();server.server_close();thread.join()
print(json.dumps({'passed':True,'capabilities':['loopback HTTP','JSON','XML','HTML standard-library parser'],'external_accounts':False}))
