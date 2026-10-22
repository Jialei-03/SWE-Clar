import json,subprocess,runpy
base=runpy.run_path('/opt/sweclar/flutter_preflight.py')['preflight']()
env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','NODE_PATH':'/opt/sweclar/websocket/node_modules'}
r=subprocess.run(['node','/opt/sweclar/capability.cjs'],env=env,capture_output=True,text=True,timeout=15,user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({**base,'websocket':json.loads(r.stdout),'passed':True,'candidate_code_loaded':False}))
