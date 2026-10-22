import json,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/vision_preflight.py'],check=True,capture_output=True,text=True,timeout=90)
report=subprocess.run([sys.executable,'-I','/opt/sweclar/report_probe.py'],user=1000,group=1000,extra_groups=[],check=True,capture_output=True,text=True,timeout=20)
print(json.dumps({'passed':True,'vision':json.loads(base.stdout),'report':json.loads(report.stdout),'candidate_code_loaded':False}))
