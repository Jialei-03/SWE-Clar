import json,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/vision_preflight.py'],capture_output=True,text=True,timeout=90,check=True)
probe=subprocess.run([sys.executable,'-I','/opt/sweclar/comfy_probe.py'],user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'},capture_output=True,text=True,timeout=90)
assert probe.returncode==0,probe.stderr[-3000:]
print(json.dumps({'passed':True,'vision':json.loads(base.stdout),'comfy':json.loads(probe.stdout),'candidate_code_loaded':False,'dependency_install_during_attempt':False}))
