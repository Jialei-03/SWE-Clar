import json,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/report_preflight.py'],check=True,capture_output=True,text=True,timeout=120)
check=subprocess.run([sys.executable,'-I','/opt/sweclar/document_health.py'],user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp'},check=True,capture_output=True,text=True,timeout=20)
print(json.dumps({'passed':True,'base':json.loads(base.stdout),'document':json.loads(check.stdout),'candidate_code_loaded':False}))
