"""Public operations only: invoke candidate builder or upstream native validation."""
import sys,json,contextlib,importlib.util
from pathlib import Path
request=json.load(sys.stdin)
if request['operation']=='build':
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('candidate',Path(request['project'])/'solution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);result=module.build_portrait_workflow(request['config'])
    print(json.dumps({'result':result,'config_after':request['config']},allow_nan=False))
else:
    with contextlib.redirect_stdout(sys.stderr):
        sys.path.insert(0,'/opt/comfy');sys.argv=['native-validation','--cpu','--fp16-unet','--fp16-text-enc','--fp32-vae','--cache-none']
        import comfy.options
        comfy.options.enable_args_parsing()
        import utils.extra_config
        import asyncio,folder_paths
        folder_paths.set_input_directory(request['input_directory'])
        user=Path(request['input_directory'])/'.comfy-user';user.mkdir(exist_ok=True);folder_paths.set_user_directory(str(user))
        import nodes,execution,server
        loop=asyncio.new_event_loop();asyncio.set_event_loop(loop);instance=server.PromptServer(loop);nodes.init_extra_nodes()
        if request['operation']=='inventory':
            mapping={'checkpoints':('CheckpointLoaderSimple','ckpt_name'),'controlnet':('ControlNetLoader','control_net_name'),'clip_vision':('CLIPVisionLoader','clip_name'),'ipadapter':('IPAdapterModelLoader','ipadapter_file')}
            result={'available_nodes':list(nodes.NODE_CLASS_MAPPINGS),'available_models':{key:nodes.NODE_CLASS_MAPPINGS[cls].INPUT_TYPES()['required'][field][0] for key,(cls,field) in mapping.items()}}
        elif request['operation']=='validate':result=execution.validate_prompt(request['prompt'])
        else:raise ValueError('Unknown public operation')
    print(json.dumps(result,allow_nan=False))
