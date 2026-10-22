import contextlib,copy,json,os,select,socket,subprocess,sys,tempfile,time,urllib.request,urllib.error,shutil,hashlib
from pathlib import Path
sys.path.insert(0,'/public_tests')
from fixtures import write_images,base_config
WHITE={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace')).resolve();os.environ['PORTRAIT_PRIVATE_SENTINEL']='private-assertion-context'
class App:
 def __init__(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.root.chmod(0o777);self.process=None
  for name in ['input','output','temp','user']:(self.root/name).mkdir(mode=0o777);(self.root/name).chmod(0o777)
  write_images(self.root/'input');self.inventory=self.worker({'operation':'inventory','input_directory':str(self.root/'input')},90)
  self.config=base_config(self.inventory);self.workflow=None;self.after=None;self.history=None;self.image_bytes=None
 def worker(self,data,timeout=30):
  result=subprocess.run([sys.executable,'-I','/public_tests/worker.py'],input=json.dumps(data),text=True,capture_output=True,cwd=ROOT,user=1000,group=1000,extra_groups=[],env=WHITE,timeout=timeout)
  assert result.returncode==0,result.stderr[-2500:];return json.loads(result.stdout)
 def build(self,config):
  result=self.worker({'operation':'build','project':str(ROOT),'config':copy.deepcopy(config)});return result['result'],result['config_after']
 def ensure_built(self):
  if self.workflow is None:self.workflow,self.after=self.build(self.config)
 def validate(self,workflow):return self.worker({'operation':'validate','input_directory':str(self.root/'input'),'prompt':workflow['prompt']},90)
 def request(self,path,body=None):
  request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  try:
   with self.opener.open(request,timeout=30) as response:return json.load(response)
  except urllib.error.HTTPError as error:raise AssertionError('Native API rejected graph: '+error.read().decode()[:1500]) from None
 def start(self):
  if self.process:return
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  self.url='http://127.0.0.1:'+str(port);self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));self.log=(self.root/'server.log').open('w')
  command=[sys.executable,'/opt/comfy/main.py','--cpu','--fp16-unet','--fp16-text-enc','--fp32-vae','--cache-none','--disable-auto-launch','--listen','127.0.0.1','--port',str(port),'--input-directory',str(self.root/'input'),'--output-directory',str(self.root/'output'),'--temp-directory',str(self.root/'temp'),'--user-directory',str(self.root/'user')]
  self.process=subprocess.Popen(command,cwd='/opt/comfy',user=1000,group=1000,extra_groups=[],env=WHITE,stdout=self.log,stderr=self.log)
  deadline=time.monotonic()+90
  while True:
   try:self.object_info=self.request('/object_info');break
   except Exception:
    assert self.process.poll() is None,(self.root/'server.log').read_text()[-2000:]
    assert time.monotonic()<deadline,'Server startup unavailable';time.sleep(.2)
 def execute(self):
  if self.history is not None:
   assert self.history.get('status',{}).get('status_str')=='success','Previously failed native execution (see protected history)'
   return self.history
  self.start();ident=self.request('/prompt',self.workflow)['prompt_id'];deadline=time.monotonic()+900
  while True:
   result=self.request('/history/'+ident).get(ident)
   if result:
    self.history=result
    errors=[m[1] for m in result.get('status',{}).get('messages',[]) if m[0]=='execution_error']
    assert result.get('status',{}).get('status_str')=='success',str([(e.get('exception_type'),e.get('exception_message')) for e in errors])
    return result
   assert self.process.poll() is None,(self.root/'server.log').read_text()[-2000:]
   assert time.monotonic()<deadline,'Weighted execution deadline exceeded';time.sleep(.5)
 def close(self):
  evidence=Path('/private/evidence')
  if evidence.is_dir():
   if hasattr(self,'log'):self.log.flush();shutil.copy2(self.root/'server.log',evidence/'server.log')
   record={'weighted_execution':self.history is not None,'history':self.history,'memory_peak_bytes':int(Path('/sys/fs/cgroup/memory.peak').read_text()) if Path('/sys/fs/cgroup/memory.peak').exists() else None}
   if self.process and self.process.poll() is None:
    status=Path('/proc/'+str(self.process.pid)+'/status').read_text();uid=next(x.split()[1:] for x in status.splitlines() if x.startswith('Uid:'));caps=int(next(x.split()[1] for x in status.splitlines() if x.startswith('CapEff:')),16)
    code="import pathlib,json;print(json.dumps([x.split('=',1)[0] for x in pathlib.Path('/proc/"+str(self.process.pid)+"/environ').read_bytes().decode().split(chr(0)) if x]))"
    result=subprocess.run([sys.executable,'-I','-c',code],user=1000,group=1000,extra_groups=[],env=WHITE,text=True,capture_output=True,check=True);keys=json.loads(result.stdout)
    assert uid==['1000']*4 and caps==0 and set(keys)<=set(WHITE) and 'PORTRAIT_PRIVATE_SENTINEL' not in keys
    record['actual_server_process']={'uid':uid,'cap_eff':caps,'environment_keys':keys}
   images=[]
   for image in (self.root/'output').rglob('*.png'):
    shutil.copy2(image,evidence/image.name);images.append({'file':image.name,'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'size':image.stat().st_size})
   record['images']=images;(evidence/'execution.json').write_text(json.dumps(record,indent=2))
  if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=15)
  if hasattr(self,'log'):self.log.close()
  self.temp.cleanup()
_APP=None
def app():
 global _APP
 if _APP is None:_APP=App()
 return _APP
def close():
 if _APP:_APP.close()
def graph():
 a=app();a.ensure_built();assert 'error' not in a.workflow,a.workflow;g=a.workflow['prompt'];assert isinstance(g,dict) and g;return g
def ids(g,*types):return [key for key,node in g.items() if node['class_type'] in types]
def ancestors(g,key):
 seen=set();todo=[key]
 while todo:
  key=todo.pop()
  if key in seen:continue
  seen.add(key)
  for value in g[key]['inputs'].values():
   if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int:todo.append(value[0])
 return seen
