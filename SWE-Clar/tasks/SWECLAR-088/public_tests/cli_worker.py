"""Generic CLI action/observation worker; no private policy assertions."""
import json,subprocess,sys,tempfile
from pathlib import Path
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='license-cli-') as temp:
 db=Path(temp)/'workflow.sqlite'
 def execute(command,value=None):
  p=subprocess.run([sys.executable,str(Path(r['project'])/'cli.py'),'--db',str(db),command],input=json.dumps(value) if value is not None else '',text=True,capture_output=True,cwd=r['project'],timeout=10)
  return {'returncode':p.returncode,'output':json.loads(p.stdout) if p.stdout.strip() else None,'stderr':p.stderr[-800:]}
 rows.append(execute('init',r['state']))
 def resolve(value):
  if isinstance(value,dict) and set(value)=={'observation','path'}:
   found=rows[value['observation']]['output']
   for key in value['path']:found=found[key]
   return found
  if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
  if isinstance(value,list):return [resolve(v) for v in value]
  return value
 for operation in r['operations']:rows.append(execute(operation['command'],resolve(operation.get('value'))))
 print(json.dumps({'observations':rows}))
