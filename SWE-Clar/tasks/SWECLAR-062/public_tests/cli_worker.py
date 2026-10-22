"""Generic CLI action/observation worker; no private policy assertions."""
import json,subprocess,sys,tempfile
from pathlib import Path
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='monthly-cli-') as temp:
 db=Path(temp)/'workflow.sqlite'
 def execute(command,value=None):
  p=subprocess.run([sys.executable,str(Path(r['project'])/'cli.py'),'--db',str(db),command],input=json.dumps(value) if value is not None else '',text=True,capture_output=True,cwd=r['project'],timeout=10)
  return {'returncode':p.returncode,'output':json.loads(p.stdout) if p.stdout.strip() else None,'stderr':p.stderr[-800:]}
 rows.append(execute('init',r['state']))
 for operation in r['operations']:rows.append(execute(operation['command'],operation.get('value')))
 print(json.dumps({'observations':rows}))
