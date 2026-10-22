import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root));calls=[]
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('trend_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        def fetch(url):
            calls.append(url)
            if request.get('fetch_error'):raise OSError('Synthetic transport failure')
            return request['csv']
        kwargs={'fetch_text':fetch} if 'csv' in request or request.get('fetch_error') else {}
        result=module.process_trend_action(request['state'],request['action'],**kwargs)
    wire.write(json.dumps({'result':result,'after':[request['state'],request['action']],'fetch_calls':calls},allow_nan=False)+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n')
