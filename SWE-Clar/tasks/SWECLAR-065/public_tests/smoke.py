import os,sys,subprocess,select,json
from urllib.request import urlopen
p=subprocess.Popen([sys.executable,'/public_tests/server.py'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PORT':'0','PYTHONDONTWRITEBYTECODE':'1'})
try:
 assert select.select([p.stdout],[],[],8)[0];url='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
 with urlopen(url) as r:assert b'app.js' in r.read()
 with urlopen(url+'/app.js') as r:assert b'React.createElement' in r.read()
 print('public React shell assets passed')
finally:p.terminate();p.wait(timeout=5)
