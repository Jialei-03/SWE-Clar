import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root))
try:
 with contextlib.redirect_stdout(sys.stderr):
  spec=importlib.util.spec_from_file_location('candidate',root/'solution.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);out=m.process_voice_event(request['state'],request['event'])
 wire.write(json.dumps({'result':out,'after':[request['state'],request['event']]})+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n')
