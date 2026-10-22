import base64,io,json,os,select,subprocess,sys,tempfile,wave
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pathlib import Path
from conftest import ROOT
class App:
 def __enter__(self):
  self.temp=tempfile.TemporaryDirectory();self.log=open(Path(self.temp.name)/'stderr','w+')
  self.process=subprocess.Popen([sys.executable,'server.py','--port','0'],cwd=ROOT,stdout=subprocess.PIPE,stderr=self.log,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
  try:
   assert select.select([self.process.stdout],[],[],10)[0],'No startup response'
   self.url='http://127.0.0.1:'+str(json.loads(self.process.stdout.readline())['port']);return self
  except BaseException:self.__exit__();raise
 def __exit__(self,*args):
  self.process.terminate()
  try:self.process.wait(timeout=5)
  except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
  self.log.close();self.temp.cleanup()
 def get(self,path,raw=False):
  with urlopen(self.url+path,timeout=10) as response:data=response.read()
  return data if raw else json.loads(data)
 def post(self,event,expected=200):
  data=event if isinstance(event,bytes) else json.dumps(event).encode()
  request=Request(self.url+'/events',data=data,headers={'Content-Type':'application/json'})
  try:response=urlopen(request,timeout=10)
  except HTTPError as error:response=error
  with response:status=response.status;out=json.load(response)
  assert status==expected,(status,out.get('error'));return out
 def setup(self):
  self.post({'type':'create_room','admin_id':'admin','room_id':'r','private':True,'access_token':'local-token','turn_limit':60})
  for user in ['speaker','listener','locked']:
   self.post({'type':'join','room_id':'r','user_id':user,'access_token':'local-token'})
  self.post({'type':'lock_pass','room_id':'r','user_id':'locked'})
  self.post({'type':'advance','room_id':'r','server_time':100})
 def inbox(self,user,room='r'):return self.get('/inbox?room_id='+room+'&user_id='+user)['packets']
def wav(samples=200,channels=1,width=2,rate=8000):
 out=io.BytesIO()
 with wave.open(out,'wb') as f:
  f.setnchannels(channels);f.setsampwidth(width);f.setframerate(rate);f.writeframes(bytes([10,40])*samples*channels)
 return out.getvalue()
