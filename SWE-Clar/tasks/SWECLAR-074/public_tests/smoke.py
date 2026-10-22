import tempfile,subprocess,sys,os,json,select,urllib.request
with tempfile.TemporaryDirectory() as d:
 subprocess.run([sys.executable,'/public_tests/demo_config.py',d+'/config.json'],check=True)
 p=subprocess.Popen([sys.executable,'server.py'],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','CONSOLE_CONFIG':d+'/config.json','CONSOLE_DATABASE':d+'/sessions.sqlite','CESIUM_ASSET_DIR':'/opt/sweclar/cesium/Build/Cesium','PORT':'0'},stdout=subprocess.PIPE,text=True)
 try:
  assert select.select([p.stdout],[],[],5)[0];url='http://127.0.0.1:'+str(json.loads(p.stdout.readline())['port'])
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  for path in ['/','/app.js','/cesium/Cesium.js']:
   with opener.open(url+path) as r:assert r.status==200 and r.read(30)
  print('Public local shell and Cesium assets passed')
 finally:p.terminate();p.wait(timeout=5)
