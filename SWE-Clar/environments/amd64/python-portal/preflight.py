"""Independent base runtime and real transaction health checks."""
import json,os,subprocess,sys
base=json.loads(subprocess.check_output([sys.executable,'-I','/opt/sweclar/web_preflight.py'],text=True));assert base['passed']
mongo=json.loads(subprocess.check_output([sys.executable,'-I','/opt/sweclar/check_mongo.py'],text=True,**({'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {})));assert mongo['passed']
print(json.dumps({'passed':True,'base':base,'mongo':mongo}))
