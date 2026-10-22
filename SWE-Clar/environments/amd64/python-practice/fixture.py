"""Prepared synthetic practice accounts, media and receipt provider."""
import hashlib,hmac,json,math,struct,wave
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit

KEY='71'*32  # Public synthetic provider key, unrelated to any credential.
PORT=38910
ROOT=Path('/tmp/sweclar-practice')

def initialize(root=ROOT):
    root.mkdir(parents=True,exist_ok=True);root.chmod(0o755)
    config={'users':[{'id':u,'login':u,'password':'fixture-only'} for u in ['user-a','user-b']],
            'products':{'quarter':{'title':'Quarter plan'},'annual':{'title':'Annual plan'}},
            'questions':[{'id':'q'+str(i),'label':'Practice metric '+str(i)} for i in range(1,7)],
            'tracks':[{'id':'tone-a','title':'Synthetic tone A','filename':'tone-a.wav','playlists':['practice']},{'id':'tone-b','title':'Synthetic tone B','filename':'tone-b.wav','playlists':['practice']}],
            'provider':'http://127.0.0.1:'+str(PORT),'provider_key':KEY}
    (root/'config.json').write_text(json.dumps(config));(root/'config.json').chmod(0o644)
    for filename,frequency in [('tone-a.wav',330),('tone-b.wav',550)]:
        with wave.open(str(root/filename),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
            w.writeframes(b''.join(struct.pack('<h',round(6000*math.sin(2*math.pi*frequency*i/24000))) for i in range(24000*20)))
        (root/filename).chmod(0o644)
    return config

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        path=urlsplit(self.path).path;status=200
        if path=='/health':data={'ready':True,'fixture':'synthetic-practice'}
        elif path.startswith('/receipts/') and unquote(path.split('/')[-1]) in {'demo-a','demo-b'}:
            ident=unquote(path.split('/')[-1]);payload={'transaction_id':ident,'user':'user-'+ident[-1],'product':'quarter','store':'alpha','status':'paid'}
            signature=hmac.new(bytes.fromhex(KEY),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest();data={'payload':payload,'signature':signature}
        else:status=404;data={'error':'unknown_fixture'}
        body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

if __name__=='__main__':
    initialize();ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
