import tempfile,subprocess,json,sys
with tempfile.TemporaryDirectory() as d:
 seed={'comments':[],'refunds':[]}
 subprocess.run([sys.executable,'cli.py',d+'/commands.sqlite','init'],input=json.dumps(seed),text=True,capture_output=True,check=True)
 r=subprocess.run([sys.executable,'cli.py',d+'/commands.sqlite','snapshot'],text=True,capture_output=True,check=True)
 assert json.loads(r.stdout)==seed;print('public SQLite initialization/reopen passed')
