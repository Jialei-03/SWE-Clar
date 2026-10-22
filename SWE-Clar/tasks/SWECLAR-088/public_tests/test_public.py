import json,subprocess,sys
from pathlib import Path
admin={'admin_id':'admin'}
r=subprocess.run([sys.executable,'-I','/public_tests/cli_worker.py'],input=json.dumps({'project':str(Path.cwd()),'state':{'admins':['admin']},'operations':[{'command':'show','value':admin},{'command':'init','value':{}},{'command':'show','value':admin},{'command':'show'},{'command':'show','value':{'admin_id':'unknown'}},{'command':'show','value':admin}]}),text=True,capture_output=True,check=True)
rows=json.loads(r.stdout)['observations'];assert all(x['returncode']==0 for x in rows),rows
assert rows[1]['output']==rows[0]['output']==rows[3]['output']==rows[6]['output']
assert all(rows[i]['output']['error']['code'] for i in (2,4,5))
print('Public SQLite initialization and persistence checks passed')
