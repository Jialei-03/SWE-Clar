import json,subprocess,sys,time
from urllib.request import urlopen
p=subprocess.Popen([sys.executable,'-I','/public_tests/development_service.py'],stdout=subprocess.DEVNULL,stderr=open('/tmp/smartlink-provider.log','ab'),user=1000,group=1000,extra_groups=[],start_new_session=True)
for _ in range(40):
    try:
        with urlopen('http://127.0.0.1:8090/health',timeout=1) as r:assert json.load(r)['ok'] is True
        print(json.dumps({'passed':True,'local_provider':'http://127.0.0.1:8090','candidate_uid':1000}));break
    except Exception:time.sleep(.1)
else:raise RuntimeError('Prepared provider not responding')
