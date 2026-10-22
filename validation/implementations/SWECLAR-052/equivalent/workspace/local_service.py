"""Synthetic provider and normalized connector for local development only."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs
import base64,json
class Handler(BaseHTTPRequestHandler):
    def reply(self,status,data):
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        if self.path=='/health':return self.reply(200,{'ok':True})
        if self.path=='/me' and self.headers.get('Authorization')=='Bearer local-token':return self.reply(200,{'id':'local-user'})
        return self.reply(401,{})
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('Content-Length',0)))
        if self.path=='/token':
            data=parse_qs(body.decode());auth='Basic '+base64.b64encode(b'local-client:local-secret').decode()
            if self.headers.get('Authorization')==auth and data.get('grant_type')==['authorization_code'] and data.get('code')==['local-code'] and data.get('redirect_uri')==['http://127.0.0.1:8090/callback']:return self.reply(200,{'access_token':'local-token','token_type':'Bearer'})
            return self.reply(400,{})
        if self.path in ['/meta','/tiktok']:
            try:data=json.loads(body)
            except Exception:return self.reply(400,{})
            return self.reply(200,{'accepted':True,'event_id':data.get('event_id')})
        return self.reply(404,{})
    def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8090),Handler).serve_forever()
