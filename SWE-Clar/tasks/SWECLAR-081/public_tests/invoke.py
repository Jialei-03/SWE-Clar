"""Public unprivileged function observation, without private assertions."""
import contextlib,importlib.util,json,sys
from pathlib import Path
request=json.load(sys.stdin);wire=sys.stdout;value=request['request']
try:
 with contextlib.redirect_stdout(sys.stderr):
  root=Path(request['project']);sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('candidate',root/'directory_planner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  try:result=m.plan_directory_update(**value);out={'result':result}
  except ValueError:out={'rejected':True}
 out['after']=value;wire.write(json.dumps(out)+'\n')
except Exception as e:wire.write(json.dumps({'error':type(e).__name__+': '+str(e)})+'\n')
