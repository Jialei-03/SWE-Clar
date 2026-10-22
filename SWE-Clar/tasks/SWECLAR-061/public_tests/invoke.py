"""Public scrypt compatibility operation, no hidden data/expectations."""
import contextlib,importlib.util,json,sys
from pathlib import Path
request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root));wire=sys.stdout
try:
 with contextlib.redirect_stdout(sys.stderr):
  spec=importlib.util.spec_from_file_location('candidate',root/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);result=m.Store.verifier(None,request['password'],request['salt'])
 wire.write(json.dumps({'result':result})+'\n')
except Exception as e:wire.write(json.dumps({'error':str(e)})+'\n')
