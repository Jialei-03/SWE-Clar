"""Neutral RPC adapter for the public domain and MQTT functions."""
import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root));sys.dont_write_bytecode=True
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('candidate_iot',root/'solution.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        result=getattr(m,request['function'])(*request['args'],**request.get('kwargs',{}))
    wire.write(json.dumps({'result':result,'after':request['args']})+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error),'after':request['args']})+'\n')
