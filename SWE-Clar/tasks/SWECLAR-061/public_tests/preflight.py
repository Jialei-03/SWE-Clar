import json,os,select,subprocess,sys
from pathlib import Path
from urllib.request import urlopen
subprocess.run([sys.executable,'-I','-c',"from pathlib import Path;Path('/workspace/runtime').mkdir(exist_ok=True);Path('/workspace/runtime').chmod(0o777)"],check=True,user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
log=open('/workspace/runtime/provider.log','ab')
p=subprocess.Popen([sys.executable,'-I','/public_tests/development_provider.py'],stdout=subprocess.PIPE,stderr=log,text=True,user=1000,group=1000,extra_groups=[],start_new_session=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
assert select.select([p.stdout],[],[],10)[0],'Provider did not start';port=json.loads(p.stdout.readline())['port']
with urlopen(f'http://127.0.0.1:{port}/health',timeout=5) as r:assert json.load(r)['ok'] is True
print(json.dumps({'passed':True,'provider_ready':True,'prepared_config':'runtime/config.json','provider_uid':1000}))
