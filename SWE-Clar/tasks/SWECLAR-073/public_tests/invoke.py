import contextlib,importlib.util,json,sys
from pathlib import Path
r=json.load(sys.stdin);wire=sys.stdout
try:
 with contextlib.redirect_stdout(sys.stderr):
  root=Path(r['project']);sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('candidate',root/'solution.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);result=m.migrate_asset_batch(r['assets'],r['taxonomy'],r['source'],r['destination'])
 print(json.dumps({'report':result,'after':[r['assets'],r['taxonomy']]}),file=wire)
except Exception as e:print(json.dumps({'error':type(e).__name__+': '+str(e)}),file=wire)
