"""Public JSONL driver; run only as the unprivileged candidate user."""
import importlib,json,os,sys,traceback
from pathlib import Path
if os.geteuid()==0:raise RuntimeError('Candidate driver cannot run as manager')
sys.path.insert(0,str(Path.cwd()))
solution=importlib.import_module('solution')
for line in sys.stdin:
 try:
  request=json.loads(line);state=request.get('state',{});action=request.get('action',{});before=json.dumps([state,action],sort_keys=True)
  store=None;transport=None
  if request.get('store'):
   from offline_store import OfflineStore
   config=request['store'];store=OfflineStore(config['root'],bytes.fromhex(config['key_hex']))
  if request.get('endpoint'):
   from sync_transport import SyncTransport
   transport=SyncTransport(request['endpoint'])
  if request.get('operation')=='read_bundle':result=store.read_bundle(request['user_id'],request['job_id'])
  elif request.get('operation')=='write_bundle':result=store.write_bundle(request['user_id'],request['job_id'],request['data'])
  else:result=solution.process_field_action(state,action,store,transport)
  response={'ok':True,'result':result,'inputs_unchanged':before==json.dumps([state,action],sort_keys=True)}
 except Exception as error:response={'ok':False,'exception':type(error).__name__,'message':str(error)}
 print(json.dumps(response),flush=True)
