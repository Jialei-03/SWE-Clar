import os,sys,json,tempfile,traceback
from pathlib import Path
if not Path('/public_tests/invoke.py').is_file():print(json.dumps({'harness_ok':False,'results':[]}));sys.exit(0)
try:import test_solution as checks
except ImportError as exc:print(json.dumps({'harness_ok':False,'results':[],'error':str(exc)}));sys.exit(0)
rows=[]
for name in sorted(n for n in dir(checks) if n.startswith('test_ru_')):
 try:
  with tempfile.TemporaryDirectory(prefix='archive-check-') as temp:getattr(checks,name)(Path(temp))
  row={'ru_id':'RU-'+name.split('_')[2],'passed':True}
 except Exception as exc:row={'ru_id':'RU-'+name.split('_')[2],'passed':False,'detail':str(exc),'trace':traceback.format_exc()[-2200:]}
 rows.append(row)
print(json.dumps({'harness_ok':True,'results':rows}))
