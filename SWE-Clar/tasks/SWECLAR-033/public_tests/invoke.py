"""Public single-call transport for the supplied Python integration interface."""
import contextlib,importlib.util,json,sys,traceback
from pathlib import Path
wire=sys.stdout
request=json.loads(sys.stdin.readline())
root=Path(request['project']);sys.path.insert(0,str(root))
def emit(value):wire.write(json.dumps(value,allow_nan=False)+'\n');wire.flush()
def fetch(url):
 emit({'kind':'fetch','url':url});reply=json.loads(sys.stdin.readline())
 if 'error' in reply:raise OSError(reply['error'])
 return reply['text']
try:
 with contextlib.redirect_stdout(sys.stderr):
  spec=importlib.util.spec_from_file_location('exhibition_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  state=request['state'];action=request['action']
  result=module.process_exhibition_action(state,action,fetch_text=fetch) if request['adapter'] else module.process_exhibition_action(state,action)
 emit({'kind':'result','value':result,'state_after':state,'action_after':action})
except Exception as e:emit({'kind':'exception','error':type(e).__name__+': '+str(e)})
