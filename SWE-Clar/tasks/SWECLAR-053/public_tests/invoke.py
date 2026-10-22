"""Neutral process adapter; no business oracle or hidden rules."""
import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root))
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('candidate_levels',root/'levels.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        result=m.analyze_levels(request['bars'],request['lookback'],**request.get('options',{}))
    wire.write(json.dumps({'result':result,'after':request['bars']},allow_nan=False)+'\n')
except Exception as error:
    wire.write(json.dumps({'error':type(error).__name__,'after':request['bars']})+'\n')
