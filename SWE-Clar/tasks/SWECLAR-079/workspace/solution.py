"""Native ComfyUI API workflow builder; complete the portrait processing paths."""
def build_portrait_workflow(config):
    if any(config.get(key) not in config.get('assets',[]) for key in ['template_asset','face_asset']):
        return {'error':{'code':'missing_local_image'}}
    graph={
        'base':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':config['models']['checkpoint']}},
        'scene':{'class_type':'LoadImage','inputs':{'image':config['template_asset']}},
        'reference':{'class_type':'LoadImage','inputs':{'image':config['face_asset']}},
        'positive':{'class_type':'CLIPTextEncode','inputs':{'clip':['base',1],'text':config['prompt']}},
        'negative':{'class_type':'CLIPTextEncode','inputs':{'clip':['base',1],'text':config['negative_prompt']}},
    }
    # Connect real preprocessing, conditioning, sampling, compositing and save nodes.
    return {'prompt':graph}
