import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/workspace')
from solution import process_smartlink_event
state={'smartlinks':{'demo':{}}};result=process_smartlink_event(state,{'type':'status'})
assert all(result['result'][key]==0 for key in ['clicks','attributed_streams','conversions'])
assert state=={'smartlinks':{'demo':{}}}
result=process_smartlink_event(state,{'type':'oauth_start','state_token':'public-state','user_id':'public-user'})
assert result['oauth_states']['public-state']['consumed'] is False
p=subprocess.run([sys.executable,'/workspace/cli.py'],input=json.dumps({'state':{},'events':[{'type':'status'}]}),text=True,capture_output=True,check=True)
assert json.loads(p.stdout)['result']['clicks']==0
print('Public status, input preservation, OAuth initiation and CLI passed.')
