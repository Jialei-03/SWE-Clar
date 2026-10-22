"""Protected media oracle; candidate imports occur only in the UID1000 worker."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,threading,hashlib
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_proxy import policy,observations,pipeline,CandidateFailure
ROOT=Path(os.environ['SWECLAR_PROJECT_DIR'])

def read_bytes(path):
 return subprocess.run([sys.executable,'-I','-c','from pathlib import Path;import sys;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())',str(path)],capture_output=True,check=True,user=1000,group=1000,extra_groups=[]).stdout

def cleanup_children(root):
 code="from pathlib import Path;import shutil,sys;p=Path(sys.argv[1]);[(shutil.rmtree(f) if f.is_dir() and not f.is_symlink() else f.unlink()) for f in p.iterdir()]"
 subprocess.run([sys.executable,'-I','-c',code,str(root)],check=True,user=1000,group=1000,extra_groups=[])

def encode(path,kind,events=()):
 frames=[]
 for i in range(160):
  rgb=bytearray(bytes((20,20+i,50) if kind=='record' else (0,0,0))*160*100)
  if i in events:
   for y in range(30,46):
    for x in range(110,126):rgb[(y*160+x)*3:(y*160+x)*3+3]=bytes((255,0,0))
  frames.append(rgb)
 subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','160x100','-r','10','-i','-','-an','-c:v','mpeg4','-threads','1','-q:v','1',str(path)],input=b''.join(frames),capture_output=True,check=True,timeout=20)

def probe(path):
 r=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height:format=duration','-of','json',str(path)],text=True,capture_output=True,check=True,timeout=10,user=1000,group=1000,extra_groups=[])
 return json.loads(r.stdout)

def pixel(path,time):
 r=subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=10,user=1000,group=1000,extra_groups=[])
 assert len(r.stdout)==3,'Clip must decode actual pixels'
 return tuple(r.stdout)

class Receiver:
 def __enter__(self):
  self.received=[];self.mode='ok';outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    data=self.rfile.read(int(self.headers['Content-Length']));digest=hashlib.sha256(data).hexdigest();outer.received.append((data,{k.lower():v for k,v in self.headers.items()}))
    body=json.dumps({'accepted':outer.mode!='reject','sha256':'wrong' if outer.mode=='wrong_hash' else digest}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.server.server_port}/clips';return self
 def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()

def invoke_cli(request,root):
 file=root/'request.json';file.write_text(json.dumps(request))
 r=subprocess.run([sys.executable,str(ROOT/'cli.py'),str(file)],user=1000,group=1000,extra_groups=[],cwd=ROOT,env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},text=True,capture_output=True,timeout=45)
 assert r.returncode==0,r.stderr[-500:]
 return json.loads(r.stdout)

def ru001(root):
 detection=root/'detection.mp4';record=root/'record.mp4'
 # Isolated integration events: zero cooldown supplied explicitly, so RU003's hidden default is not needed.
 encode(detection,'detect',[10,60,150]);encode(record,'record')
 expected=[(1,0,3),(6,1,8),(15,10,16)]
 original={(start,t):pixel(record,start+t) for _,start,end in expected for t in [.2,(end-start)/2,end-start-.2]}
 with Receiver() as receiver:
  request={'detection_video':str(detection),'recording_video':str(record),'output_dir':str(root/'output'),'line_x':80,'delivery_url':receiver.url,'cooldown_seconds':0}
  result=invoke_cli(request,root);assert len(result['clips'])==len(receiver.received)==3
  for clip,(trigger,start,end),(body,headers) in zip(result['clips'],expected,receiver.received):
   assert clip['trigger']==trigger and clip['start']==start and clip['end']==end
   relative=Path(clip['file']);assert not relative.is_absolute() and '..' not in relative.parts
   path=root/'output'/relative
   metadata=probe(path);assert abs(float(metadata['format']['duration'])-(end-start))<=.12
   assert metadata['streams'][0]['width']>0 and metadata['streams'][0]['height']>0
   for time in [.2,(end-start)/2,end-start-.2]:
    actual=pixel(path,time);wanted=original[(start,time)];assert max(abs(a-b) for a,b in zip(actual,wanted))<=8,(actual,wanted)
   assert body==read_bytes(path) and headers['content-type']=='video/mp4'
   assert headers['x-content-sha256']==hashlib.sha256(body).hexdigest()==clip['sha256']
   assert headers.get('x-clip-id'), 'Missing public delivery ID header'
  manifest=json.loads(read_bytes(root/'output/manifest.json'));assert len(manifest['clips'])==len(result['clips'])
  for stored,returned in zip(manifest['clips'],result['clips']):
   for field in ['file','trigger','start','end','sha256']:assert stored[field]==returned[field]
  for mode in ['wrong_hash','reject']:
   receiver.mode=mode;request['output_dir']=str(root/mode)
   try:pipeline(**request)
   except CandidateFailure:pass
   else:raise AssertionError('Unacknowledged delivery accepted')
   assert not Path(request['output_dir']).exists()
  request['output_dir']=str(root/'output');before=read_bytes(root/'output/manifest.json');count=len(receiver.received)
  try:pipeline(**request)
  except CandidateFailure:pass
  else:raise AssertionError('Existing output accepted')
  assert read_bytes(root/'output/manifest.json')==before and len(receiver.received)==count
 sample=[{'timestamp':0,'goal_candidate':False,'metadata':{'note':'synthetic'}}]
 assert policy(sample)==policy(sample)==[]

def ru002(root):
 assert policy([{'timestamp':0,'goal_candidate':False},{'timestamp':2,'goal_candidate':True}])==[2]
 assert policy([{'timestamp':7.25,'goal_candidate':True}])==[7.25]
 path=root/'detect.mp4';encode(path,'detect',[10]);rows=observations(path,80)
 assert len(rows)==160 and [r['timestamp'] for r in rows if r['goal_candidate']]==[1]
 # The same decoded red target is on opposite sides of these two lines.
 # An any-red classifier must fail the second observation.
 rows=observations(path,110)
 assert len(rows)==160 and [r['timestamp'] for r in rows if r['goal_candidate']]==[1]
 rows=observations(path,130)
 assert len(rows)==160 and not any(r['goal_candidate'] for r in rows)

def ru003(root):
 sample=[{'timestamp':t,'goal_candidate':True} for t in [0,1,4.999,5,5.1,10]]
 assert policy(sample)==[0,5,10]
 sample=[{'timestamp':t,'goal_candidate':v} for t,v in [(1,True),(1.1,False),(2.9,True),(3,True),(5,True)]]
 assert policy(sample,cooldown_seconds=2)==[1,3,5]
 assert policy(sample,cooldown_seconds=0)==[1,2.9,3,5]

def main():
 if not Path('/public_tests/invoke.py').is_file():return {'harness_ok':False,'error':'Missing benchmark invocation helper','results':[]}
 rows=[]
 for index,test in enumerate([ru001,ru002,ru003],1):
  with tempfile.TemporaryDirectory(prefix='video-input-') as temp:
   root=Path(temp);root.chmod(0o777)
   try:test(root);passed=True;detail='passed'
   except (TimeoutError,subprocess.TimeoutExpired):return {'harness_ok':False,'error':'Unattributed timeout; reproduce before scoring','results':[]}
   except Exception as error:passed=False;detail=type(error).__name__+': '+str(error)
   finally:cleanup_children(root)
   rows.append({'ru_id':f'RU-{index:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
