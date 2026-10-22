import os,sys,json,subprocess,select,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
with tempfile.TemporaryDirectory() as d:
 p=subprocess.Popen([sys.executable,'server.py'],stdout=subprocess.PIPE,text=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','FOOD_CONFIG':str(Path('runtime/config.json').resolve()),'FOOD_DATABASE':d+'/db.sqlite','PORT':'0','PYTHONDONTWRITEBYTECODE':'1'})
 try:
  assert select.select([p.stdout],[],[],8)[0];url='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
  for path in ['/feed','/pins?mode=personal','/pins?mode=friends']:
   with urlopen(Request(url+path,headers={'Authorization':'Bearer local-alice'})) as r:assert json.load(r)==[]
  with urlopen(url) as r:assert b'leaflet' in r.read()
  print('public baseline passed')
 finally:p.terminate();p.wait(timeout=5)
