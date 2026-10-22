"""Public transport: load candidate modules only inside the ordinary process."""
from pathlib import Path
import contextlib,importlib.util,io,json,sys,sysconfig
sys.dont_write_bytecode=True
IMPORT_ROOTS=[Path(sysconfig.get_paths()[name]).resolve() for name in ('stdlib','purelib','platlib')]
wire=sys.stdout;request=json.loads(sys.stdin.readline());root=Path(request['project']);sys.path.insert(0,str(root))
try:
 name=request['operation'];capture=io.StringIO()
 with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
  if name=='policy':
   spec=importlib.util.spec_from_file_location('candidate_policy',root/'src/goal_policy.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   def guard(event,args):
    if event=='open':
     # Permit ordinary lazy imports from the prepared Python runtime, not arbitrary file reads.
     frame=sys._getframe(1);loading=False
     while frame:
      if frame.f_globals.get('__name__','').startswith('importlib.'):loading=True;break
      frame=frame.f_back
     path=Path(args[0]).resolve() if isinstance(args[0],str) else None
     if loading and path is not None and any(path.is_relative_to(base) for base in IMPORT_ROOTS) and not (args[2]&3):return
     raise RuntimeError('Policy attempted file I/O')
    if event.startswith(('socket.','subprocess.','os.system','os.spawn','os.exec','os.fork')):raise RuntimeError('Policy attempted forbidden I/O')
   sys.addaudithook(guard)
   result=module.detect_goal_events(request['frames'],**request.get('options',{}))
  else:
   import pipeline
   if name=='observations':result=pipeline.observations(request['video'],request['line_x'])
   elif name=='pipeline':result=pipeline.run_pipeline(**request['arguments'])
   else:raise ValueError('Unsupported public entry')
 if name=='policy' and capture.getvalue():raise RuntimeError('Policy wrote console output')
 wire.write(json.dumps({'result':result,'after_frames':request.get('frames')},allow_nan=False)+'\n');wire.flush()
except Exception as error:
 wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n');wire.flush()
