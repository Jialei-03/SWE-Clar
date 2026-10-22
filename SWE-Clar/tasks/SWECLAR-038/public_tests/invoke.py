"""Public ordinary-user invocation transport; contains no hidden oracle."""
import contextlib, importlib.util, json, signal, sys
from pathlib import Path
request=json.loads(sys.stdin.read()); root=Path(request['project']); sys.path.insert(0,str(root)); wire=sys.stdout
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('candidate',root/'solution.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        signal.setitimer(signal.ITIMER_PROF,15)
        result=module.optimize_lineups(request['players'],request['limit'],request['mode'])
        signal.setitimer(signal.ITIMER_PROF,0)
    # Non-finite inputs must reach validation; encode the input snapshot as text
    # while keeping the actual candidate result strict JSON.
    wire.write(json.dumps({'result':result,'after_json':json.dumps(request['players'],sort_keys=True)},allow_nan=False))
except Exception as error:
    signal.setitimer(signal.ITIMER_PROF,0)
    wire.write(json.dumps({'error':type(error).__name__+': '+str(error)}))
