import json,subprocess,sys
from pathlib import Path
r=subprocess.run([sys.executable,'-I','/public_tests/cli_worker.py'],input=json.dumps({'project':str(Path.cwd()),'state':{'users':{},'credits':{}},'operations':[{'command':'show'},{'command':'init','value':{}},{'command':'show'}]}),text=True,capture_output=True,check=True)
rows=json.loads(r.stdout)['observations'];assert all(x['returncode']==0 for x in rows),rows
assert rows[1]['output']==rows[0]['output']==rows[3]['output'];assert rows[2]['output']['error']['code']
print('Public SQLite initialization and persistence checks passed')
