import json,sys,importlib.util
value=json.load(sys.stdin);spec=importlib.util.spec_from_file_location('candidate',value['project']+'/solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
out=module.process_backend_command(value['state'],value['command']);json.dump({'result':out,'state_after':value['state'],'command_after':value['command']},sys.stdout,allow_nan=False)
