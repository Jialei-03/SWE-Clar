import base64,hashlib,json,os,subprocess,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
identity={'user':1000,'group':1000,'extra_groups':[]}
def call(state,action,config,endpoint=None):
 request={'state':state,'action':action,'store':config,'endpoint':endpoint}
 r=subprocess.run([sys.executable,'-I','/public_tests/component_runner.py'],input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=10,**identity)
 assert r.returncode==0,r.stderr
 out=json.loads(r.stdout);assert out['ok'] and out['inputs_unchanged'],out
 return out['result']
def read_as_user(path):
 r=subprocess.run([sys.executable,'-I','-c','import base64,pathlib,sys;print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())',str(path)],capture_output=True,text=True,check=True,**identity)
 return base64.b64decode(r.stdout)
def raw_call(request):
 r=subprocess.run([sys.executable,'-I','/public_tests/component_runner.py'],input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=10,**identity)
 assert r.returncode==0,r.stderr
 return json.loads(r.stdout)
