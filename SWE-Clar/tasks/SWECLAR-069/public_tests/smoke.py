import sys,subprocess,json,tempfile
with tempfile.TemporaryDirectory() as d:
 seed={'users':{},'jobs':{},'ledger':[],'processed_ids':[]}
 p=subprocess.run([sys.executable,'cli.py',d+'/ledger.sqlite','init'],input=json.dumps(seed),text=True,capture_output=True,check=True)
 q=subprocess.run([sys.executable,'cli.py',d+'/ledger.sqlite','snapshot'],text=True,capture_output=True,check=True)
 assert json.loads(q.stdout)['ledger']==[] and json.loads(q.stdout)['users']=={}
 print('public persistent CLI initialization passed')
