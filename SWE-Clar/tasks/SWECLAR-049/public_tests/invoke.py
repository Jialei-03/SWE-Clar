import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root))
try:
 with contextlib.redirect_stdout(sys.stderr):
  spec=importlib.util.spec_from_file_location('intake_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  result=module.process_mentor_event(request['database'],request['event'])
 wire.write(json.dumps({'result':result,'after':request['event']},allow_nan=False)+'\n')
except Exception as e:wire.write(json.dumps({'error':type(e).__name__+': '+str(e)})+'\n')
