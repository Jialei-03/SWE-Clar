"""Real upstream API/queue IO preflight; weighted portrait execution is separate evidence."""
import json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
from PIL import Image
assert os.getuid()==1000
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp)
 for name in ['input','output','user','temp']:(root/name).mkdir()
 Image.new('RGB',(32,32),(30,70,120)).save(root/'input/probe.png')
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
 command=[sys.executable,'/opt/comfy/main.py','--cpu','--fp16-unet','--fp16-text-enc','--fp32-vae','--cache-none','--disable-auto-launch','--listen','127.0.0.1','--port',str(port),'--input-directory',str(root/'input'),'--output-directory',str(root/'output'),'--user-directory',str(root/'user'),'--temp-directory',str(root/'temp')]
 log=(root/'server.log').open('w');p=subprocess.Popen(command,env=env,stdout=log,stderr=log)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));url='http://127.0.0.1:'+str(port)
 def request(path,body=None):
  q=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  with opener.open(q,timeout=5) as response:return json.load(response)
 try:
  deadline=time.monotonic()+60
  while True:
   try:info=request('/object_info');break
   except Exception:
    assert p.poll() is None,(root/'server.log').read_text()[-2500:]
    assert time.monotonic()<deadline,'ComfyUI startup timeout';time.sleep(.2)
  required=['CheckpointLoaderSimple','LoadImage','ImageCrop','ImageScale','CLIPTextEncode','CLIPVisionLoader','ControlNetLoader','ControlNetApplyAdvanced','Canny','KSampler','VAEEncode','VAEDecode','VAEDecodeTiled','SolidMask','MaskComposite','ImageCompositeMasked','SaveImage','IPAdapterModelLoader','IPAdapterAdvanced']
  assert set(required)<=set(info),sorted(set(required)-set(info))
  prompt={'read':{'class_type':'LoadImage','inputs':{'image':'probe.png'}},'write':{'class_type':'SaveImage','inputs':{'images':['read',0],'filename_prefix':'preflight'}}}
  ident=request('/prompt',{'prompt':prompt})['prompt_id'];deadline=time.monotonic()+20
  while not (history:=request('/history/'+ident).get(ident)):
   assert time.monotonic()<deadline;time.sleep(.1)
  images=[f for values in history['outputs'].values() for f in values.get('images',[])];assert len(images)==1
  with Image.open(root/'output'/images[0]['subfolder']/images[0]['filename']) as im:assert im.size==(32,32) and im.getpixel((0,0))==(30,70,120)
  print(json.dumps({'passed':True,'uid':os.getuid(),'real_object_info_nodes':len(info),'required_classes_available':required,'native_queue_image_io':True,'weighted_portrait_execution':'not asserted by environment IO preflight','models':[{'file':str(f.relative_to('/opt/comfy/models')),'size':f.stat().st_size} for f in Path('/opt/comfy/models').rglob('*.safetensors')]}))
 finally:
  p.terminate();p.wait(timeout=10);log.close()
