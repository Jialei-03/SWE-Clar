import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
root=Path('/workspace/runtime');root.mkdir(exist_ok=True);log=open(root/'provider.log','ab')
subprocess.Popen([sys.executable,'-I','/public_tests/provider_service.py','23083'],stdout=log,stderr=log,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
url='http://127.0.0.1:23083/network'
for _ in range(50):
 try:
  with urllib.request.urlopen(urllib.request.Request(url,data=b'{"start_node":"s"}',headers={'Content-Type':'application/json'}),timeout=1) as r:assert 'nodes' in json.load(r)
  break
 except Exception:time.sleep(.05)
else:raise RuntimeError('local graph unavailable')
print(json.dumps({'ready':True,'graph_url':url}))
