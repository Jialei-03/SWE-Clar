import json,sys,importlib.util
value=json.load(sys.stdin);spec=importlib.util.spec_from_file_location('candidate',value['project']+'/solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.process_marketplace_action(value['state'],value['action']);json.dump({'result':result,'state_after':value['state'],'action_after':value['action']},sys.stdout,allow_nan=False)
