"""Public smoke test of the provided startup, login, and visible API contract."""
import json,os,select,subprocess,sys,urllib.request,urllib.error
from pathlib import Path
p=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('start.py'))],env={**os.environ,'PORT':'0'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
 if not select.select([p.stdout],[],[],12)[0]:raise AssertionError('Portal did not report its listening port')
 line=p.stdout.readline()
 if not line:raise AssertionError('Portal exited before startup')
 url='http://127.0.0.1:'+str(json.loads(line)['port'])
 client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with client.open(url,timeout=5) as r:assert r.status==200 and b'<html' in r.read().lower()
 req=urllib.request.Request(url+'/login',data=json.dumps({'user_id':'sample-admin','centre_id':'demo','pin':'2468'}).encode(),headers={'Content-Type':'application/json'})
 with client.open(req,timeout=5) as r:token=json.load(r)['token'];assert isinstance(token,str) and token
 req=urllib.request.Request(url+'/api/records?module=daily_chart',headers={'Authorization':'Bearer '+token})
 with client.open(req,timeout=5) as r:assert isinstance(json.load(r),list)
 print(json.dumps({'passed':True,'checks':['provided startup','portal page','synthetic login','authenticated records API']}))
finally:
 if p.poll() is None:p.terminate();p.wait(timeout=10)
