import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root));calls=[]
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('cashless_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        def upload(events):
            calls.append(events)
            if request.get('upload_error'):raise OSError('Synthetic upload failure')
            return request['reply']
        kwargs={'upload_events':upload} if 'reply' in request or request.get('upload_error') else {}
        result=module.process_cashless_action(request['state'],request['action'],**kwargs)
    json.dumps(result,allow_nan=False)
    wire.write(json.dumps({'result':result,'after':json.dumps([request['state'],request['action']],sort_keys=True),'upload_calls':calls})+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n')
