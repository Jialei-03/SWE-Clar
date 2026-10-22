import json,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/vision_preflight.py'],check=True,capture_output=True,text=True,timeout=90)
probe=subprocess.run([sys.executable,'-I','/opt/sweclar/cesium_probe.py'],user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PLAYWRIGHT_BROWSERS_PATH':'/ms-playwright'},check=True,capture_output=True,text=True,timeout=45)
print(json.dumps({'passed':True,'vision':json.loads(base.stdout),'cesium':json.loads(probe.stdout),'candidate_code_loaded':False}))
