import contextlib,importlib.util,json,sys,traceback
from pathlib import Path
r=json.load(sys.stdin);sys.path.insert(0,r['project'])
with contextlib.redirect_stdout(sys.stderr):
 try:
  spec=importlib.util.spec_from_file_location('candidate',Path(r['project'])/'calculator.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);value=m.calculate(r['values']);out={'value':value,'after':r['values']}
 except Exception as e:out={'error':str(e),'after':r['values']}
print(json.dumps(out,allow_nan=False))
