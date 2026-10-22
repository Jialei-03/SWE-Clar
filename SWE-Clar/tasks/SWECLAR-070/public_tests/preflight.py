import json,os,subprocess,sys,urllib.request,time
from pathlib import Path
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
root=Path('/workspace/runtime');root.mkdir(exist_ok=True)
url='http://127.0.0.1:23070';config={'geocoding_url':url+'/maps/api/geocode/json','solar_url':url+'/v1/buildingInsights:findClosest','api_key':'synthetic-provider-key','pricing':{'roof_type':{'flat':1,'pitched':2},'material':{'tile':3},'extras':{'cleanup':.5}}}
p=root/'roof-config.json';p.write_text(json.dumps(config));p.chmod(0o600)
log=open(root/'provider.log','ab');subprocess.Popen([sys.executable,'-I','/public_tests/provider_service.py','23070'],stdout=log,stderr=log,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
for _ in range(50):
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'/maps/api/geocode/json?address=Synthetic%20address%20A',timeout=1) as r:assert json.load(r)['status']=='OK'
  break
 except Exception:time.sleep(.05)
else:raise RuntimeError('local provider unavailable')
print(json.dumps({'ready':True,'provider':'synthetic loopback HTTP','config':str(p),'database':str(root/'roof.sqlite')}))
