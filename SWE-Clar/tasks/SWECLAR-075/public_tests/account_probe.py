"""Neutral adapter recording real scrypt calls by the submitted registration code."""
import os,sys,json,hashlib
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
for key in list(os.environ):
 if key not in ['PATH','HOME']:del os.environ[key]
project,config,database=sys.argv[1:];calls=[];original=hashlib.scrypt
def wrapped(password,**kwargs):
 result=original(password,**kwargs);calls.append({'salt':kwargs['salt'].hex(),'result':result.hex()});return result
hashlib.scrypt=wrapped;sys.path.insert(0,project)
from store import Store
store=Store(database,json.load(open(config)));account=store.register({'email':'probe@example.test','password':'synthetic-pass'})
print(json.dumps({'account':account,'scrypt_calls':calls}))
