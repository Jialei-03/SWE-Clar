import contextlib,importlib.util,json,sys
from pathlib import Path
wire=sys.stdout;request=json.load(sys.stdin);root=Path(request['project']);sys.path.insert(0,str(root))
try:
    with contextlib.redirect_stdout(sys.stderr):
        from pipeline_client import PipelineClient
        config=request['service'];client=PipelineClient(config['source_urls'],config['destination_urls'],config['outreach_url'],config.get('token'))
        spec=importlib.util.spec_from_file_location('pipeline_candidate',root/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.process_pipeline_event(request['state'],request['action'],client)
    wire.write(json.dumps({'result':result,'after':[request['state'],request['action']]},allow_nan=False)+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error)})+'\n')
