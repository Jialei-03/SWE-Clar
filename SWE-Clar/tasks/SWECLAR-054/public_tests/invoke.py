import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;service=None;module=None
for line in sys.stdin:
 try:
  r=json.loads(line)
  with contextlib.redirect_stdout(sys.stderr):
   if module is None:
    root=Path(r['project']);sys.path.insert(0,str(root));spec=importlib.util.spec_from_file_location('candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   if r.get('configure'):
    from music_client import MusicClient
    service=MusicClient(**r['configure']);out={'configured':True}
   else:
    result=module.process_presave_action(r['state'],r['action'],service if r.get('service') else None)
    out={'result':result,'after':[r['state'],r['action']]}
  wire.write(json.dumps(out)+'\n');wire.flush()
 except Exception as e:wire.write(json.dumps({'error':type(e).__name__+': '+str(e)})+'\n');wire.flush()
