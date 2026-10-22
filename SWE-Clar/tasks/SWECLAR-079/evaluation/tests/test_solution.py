import copy,io,json
from PIL import Image
from support import app,graph,ids,ancestors

def samplers(g):
 path=set().union(*(ancestors(g,k) for k in ids(g,'SaveImage')))
 values=[k for k in ids(g,'KSampler','KSamplerAdvanced') if k in path]
 assert values,'No native sampler on saved output path'
 return values
def accepts_any(values,check):
 errors=[]
 for value in values:
  try:check(value);return
  except (AssertionError,KeyError) as e:errors.append(str(e))
 raise AssertionError('No output sampler satisfies required conditioning: '+repr(errors))
def error_result(result):assert isinstance(result.get('error',{}).get('code'),str) and result['error']['code'] and not result.get('prompt'),result

def test_ru_001_native_execution():
 a=app();g=graph();assert a.after==a.config,'Builder mutated configuration'
 assert all(isinstance(k,str) and isinstance(v,dict) and isinstance(v.get('inputs'),dict) for k,v in g.items())
 assert a.validate(a.workflow)[0],'Upstream ComfyUI validation failed'
 history=a.execute();assert history['outputs'],'Real upstream execution produced no output'

def test_ru_002_image_prompt_inputs():
 a=app();g=graph()
 def check(key):
  path=ancestors(g,key)
  for asset in [a.config['template_asset'],a.config['face_asset']]:assert any(k in path and g[k]['inputs'].get('image')==asset for k in ids(g,'LoadImage')),asset
  for text in [a.config['prompt'],a.config['negative_prompt']]:assert any(k in path and g[k]['inputs'].get('text')==text for k in ids(g,'CLIPTextEncode')),text
 accepts_any(samplers(g),check)
 config=copy.deepcopy(a.config);config['assets']=['template.png'];out,after=a.build(config);error_result(out);assert after==config

def conditioning(g,key,config):
 s=g[key]['inputs'];model_path=ancestors(g,s['model'][0]);condition_path=ancestors(g,s['positive'][0])|ancestors(g,s['negative'][0])
 adapters=[k for k in model_path if g[k]['class_type'] in ['IPAdapterAdvanced','IPAdapter']];assert adapters,'Identity adapter is not connected to sampler model'
 identity=g[adapters[0]]['inputs'];assert identity.get('weight',0)>0 and identity.get('end_at',0)>identity.get('start_at',0)
 crop_path=ancestors(g,identity['image'][0]);crops=[k for k in ids(g,'ImageCrop') if k in crop_path];assert crops
 crop=g[crops[0]]['inputs'];assert all(crop.get(k)==v for k,v in config['face_crop'].items())
 assert any(g[k]['inputs'].get('image')==config['face_asset'] for k in ancestors(g,crop['image'][0]) if g[k]['class_type']=='LoadImage')
 controls=[k for k in condition_path if g[k]['class_type'] in ['ControlNetApply','ControlNetApplyAdvanced']];assert controls
 control=g[controls[0]]['inputs'];assert control.get('strength',0)>0
 if g[controls[0]]['class_type']=='ControlNetApplyAdvanced':assert control.get('end_percent',1)>control.get('start_percent',0)
 edges=[k for k in ancestors(g,control['image'][0]) if g[k]['class_type']=='Canny'];assert edges
 assert any(g[k]['inputs'].get('image')==config['template_asset'] for k in ancestors(g,edges[0]) if g[k]['class_type']=='LoadImage')

def test_ru_003_real_conditioning_paths():
 a=app();g=graph();accepts_any(samplers(g),lambda key:conditioning(g,key,a.config))

def test_ru_004_pixels_and_output():
 a=app();g=graph();saved=ids(g,'SaveImage');assert len(saved)==1;assert samplers(g),'Save path bypasses sampling'
 history=a.execute();files=[d for value in history['outputs'].values() for d in value.get('images',[])];assert len(files)==1,files
 descriptor=files[0];image=Image.open(a.root/'output'/descriptor.get('subfolder','')/descriptor['filename']).convert('RGB');assert image.size==(a.config['width'],a.config['height'])
 template=Image.open(a.root/'input/template.png').convert('RGB').resize(image.size,Image.Resampling.NEAREST);box=a.config['edit_box'];x,y,w,h=[box[k] for k in ['x','y','width','height']]
 for bounds in [(0,0,image.width,y),(0,y,x,y+h),(x+w,y,image.width,y+h),(0,y+h,image.width,image.height)]:assert image.crop(bounds).tobytes()==template.crop(bounds).tobytes(),'Exterior template pixels changed'
 assert image.crop((x,y,x+w,y+h)).tobytes()!=template.crop((x,y,x+w,y+h)).tobytes(),'Generated image did not contribute'
 invalid=copy.deepcopy(a.config);invalid.update(width=512,height=512);out,after=a.build(invalid);error_result(out);assert after==invalid

def test_ru_005_inventory_and_decode():
 a=app()
 for memory,kind in [(16,'VAEDecodeTiled'),(24,'VAEDecode')]:
  config=copy.deepcopy(a.config);config['vram_gb']=memory;out,after=a.build(config);assert after==config and 'error' not in out
  g=out['prompt'];assert all(n['class_type'] in config['available_nodes'] for n in g.values())
  output_path=set().union(*(ancestors(g,k) for k in ids(g,'SaveImage')))
  decode=[k for k in ids(g,kind) if k in output_path];assert any(set(samplers(g))&ancestors(g,k) for k in decode)
  valid=a.validate(out);assert valid[0],valid
 config=copy.deepcopy(a.config);config['available_nodes']=[n for n in config['available_nodes'] if n!='VAEDecodeTiled'];out,_=a.build(config);error_result(out)
 config=copy.deepcopy(a.config);config['available_models']['ipadapter']=[];out,_=a.build(config);error_result(out)
