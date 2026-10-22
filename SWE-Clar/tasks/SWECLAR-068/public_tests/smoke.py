import os,sys,subprocess,select,json
from urllib.request import urlopen
p=subprocess.Popen([sys.executable,'server.py'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PORT':'0','PYTHONDONTWRITEBYTECODE':'1'})
try:
 assert select.select([p.stdout],[],[],8)[0];url='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
 with urlopen(url) as r:assert b'<svg' in r.read()
 print('public SVG adapter shell passed')
finally:p.terminate();p.wait(timeout=5)
