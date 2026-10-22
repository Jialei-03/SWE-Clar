import json,os,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/base_preflight.py'],capture_output=True,text=True,check=True)
identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
r=subprocess.run([sys.executable,'-I','/opt/sweclar/crypto_health.py'],capture_output=True,text=True,check=True,**identity)
result=json.loads(base.stdout);result['crypto']=json.loads(r.stdout);assert result['passed'] and result['crypto']['passed'];print(json.dumps(result))
