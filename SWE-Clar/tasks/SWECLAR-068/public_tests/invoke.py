import json,sys,importlib.util
value=json.load(sys.stdin);spec=importlib.util.spec_from_file_location('candidate',value['project']+'/solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.evaluate_indicator(value['config'],value['context']);json.dump({'result':result,'config_after':value['config'],'context_after':value['context']},sys.stdout,allow_nan=False)
