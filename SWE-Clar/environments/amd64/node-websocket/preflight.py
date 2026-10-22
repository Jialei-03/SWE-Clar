import json,subprocess
r=subprocess.run(['node','/opt/sweclar/capability.cjs'],capture_output=True,text=True,timeout=15,user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({'passed':True,'capability':json.loads(r.stdout),'candidate_code_loaded':False}))
