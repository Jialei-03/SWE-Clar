"""Single-call public transport for the two supported library interfaces."""
import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.loads(sys.stdin.readline());root=Path(request['project']);sys.path.insert(0,str(root))
try:
 with contextlib.redirect_stdout(sys.stderr):
  spec=importlib.util.spec_from_file_location('listing_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  if request['function'] not in {'scrape','transform'}:raise ValueError('Unsupported integration entry')
  result=getattr(module,request['function'])(request['values'])
 wire.write(json.dumps({'result':result,'after':request['values']},allow_nan=False)+'\n');wire.flush()
except Exception as error:
 wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n');wire.flush()
