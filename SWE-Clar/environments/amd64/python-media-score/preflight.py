import json,os,subprocess,sys
base=json.loads(subprocess.check_output([sys.executable,'-I','/opt/sweclar/media_preflight.py'],text=True));assert base['passed']
score=json.loads(subprocess.check_output([sys.executable,'-I','/opt/sweclar/score_health.py'],text=True,**({'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {})));assert score['passed']
print(json.dumps({'passed':True,'media':base,'score':score}))
