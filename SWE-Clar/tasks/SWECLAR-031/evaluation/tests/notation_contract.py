from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from functools import partial
import json,os,sys,shutil,tempfile,subprocess,threading,struct,math,wave,select,urllib.request
from pypdf import PdfReader
import mido
def identity():return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
sys.path.insert(0,str(TESTS))
from pdf_score import observe,OCRUnavailable
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass

def fixture(work):
 work.mkdir(exist_ok=True)
 notes=[60,64,67,72];track=b'\x00\xff\x51\x03\x07\xa1\x20'
 def vlq(n):
  result=[n&127];n>>=7
  while n:result.insert(0,(n&127)|128);n>>=7
  return bytes(result)
 for i,n in enumerate(notes):track+=vlq(192 if i else 0)+bytes([0x90,n,95])+vlq(960)+bytes([0x80,n,0])
 track+=b'\0\xff\x2f\0';(work/'fixture.mid').write_bytes(b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+struct.pack('>I',len(track))+track)
 raw=bytearray();rate=24000
 for i in range(6*rate):
  t=i/rate;j=int(t/1.2);v=0;local=t-j*1.2
  if j<4 and local<1:v=int(8000*min(1,local/.015,(1-local)/.015)*math.sin(2*math.pi*440*2**((notes[j]-69)/12)*local))
  raw+=struct.pack('<h',v)
 with wave.open(str(work/'fixture.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw)
 p=subprocess.run([os.environ.get('FFMPEG_BIN','ffmpeg'),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=20','-i',str(work/'fixture.wav'),'-t','6','-c:v','libvpx-vp9','-deadline','realtime','-cpu-used','8','-pix_fmt','yuv420p','-c:a','libopus',str(work/'fixture.webm')],capture_output=True,text=True,timeout=30);assert p.returncode==0,p.stderr
 (work/'config.json').write_text(json.dumps({'charts':[{'id':'fixture','title':'Independent synthetic practice','midi':'runtime/fixture.mid','recording':'runtime/fixture.webm'}]}))
def exported(work):
 result={};midi=mido.MidiFile(work/'exports/chart.mid');clock=0;starts=[];ends=[]
 for message in midi:
  clock+=message.time
  if message.type=='note_on' and message.velocity>0:starts.append((message.note,round(clock,4)))
  if message.type=='note_off' or message.type=='note_on' and message.velocity==0:ends.append((message.note,round(clock,4)))
 result['midi']=starts==[(72,0.0),(76,1.2),(79,2.4),(84,3.6)] and ends==[(72,1.0),(76,2.2),(79,3.4),(84,4.6)]
 pdf=observe(work/'exports/chart.pdf',expected_labels=['C5','E5','G5','C6'])
 labels=all(n in __import__('re').findall(r'[A-G](?:#|b)?-?\d+',pdf['labels']) for n in ['C5','E5','G5','C6'])
 staff=any(len(s['heads'])==4 and all(abs(h['staff_steps']-expected)<.22 for h,expected in zip(s['heads'],[1.5,.5,-.5,-2])) for s in pdf['staves'])
 result['pdf']=labels and staff

 return result

def main():
 if not shutil.which(os.environ.get('FFMPEG_BIN','ffmpeg')):return {'harness_ok':False,'infrastructure_errors':['FFmpeg H.264/AAC required'],'results':[]}
 with tempfile.TemporaryDirectory(prefix='sweclar-notation-') as temp:
  Path(temp).chmod(0o755);work=Path(temp)/'source';shutil.copytree(ROOT,work,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__'));fixture(work/'runtime');(work/'browser-downloads').mkdir();
  if os.geteuid()==0:
   for q in [work,*work.rglob('*')]:os.chown(q,1000,1000)
  exports=Path(temp)/'exports';exports.mkdir(mode=0o700);env={**os.environ,'HOME':str(work),'NOTATION_EXPORTS':str(exports),'UI_BROWSER_HOME':str(work),'UI_BROWSER_WRAPPER':str(Path('/public_tests/browser_launch.py') if Path('/public_tests/browser_launch.py').is_file() else TESTS.parent/'public_tests/browser_launch.py')}
  build=subprocess.run([os.environ.get('NODE_BIN','node'),'build.mjs',str(work/'dist')],cwd=work,env=env,capture_output=True,text=True,timeout=30,**identity())
  if build.returncode:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':build.stderr[-700:]} for i in range(1,6)]}
  server=subprocess.Popen([sys.executable,str(work/'serve.py'),str(work/'dist')],env={**env,'PORT':'0'},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**identity())
  if not select.select([server.stdout],[],[],5)[0]:server.terminate();server.wait();raise RuntimeError('static server unavailable')
  port=server.stdout.readline().strip();assert port.isdigit(),'static server failed'
  url='http://127.0.0.1:'+port
  try:
   p=subprocess.run([os.environ.get('NODE_BIN','node'),str(TESTS/'notation_probe.cjs'),url],cwd=work,env=env,capture_output=True,text=True,timeout=65)
   report=json.loads(p.stdout) if p.returncode==0 else {'errors':[p.stderr[-1400:]]}
   expected=(work/'runtime/fixture.webm').read_bytes()[100:200]
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(url+'/runtime/fixture.webm',headers={'Range':'bytes=100-199'}),timeout=5) as response:report['range']=response.status==206 and response.read()==expected

   try:files=exported(Path(temp))
   except OCRUnavailable as e:return {'harness_ok':False,'infrastructure_errors':[str(e)],'results':[]}
   except Exception as e:files={'midi':False,'pdf':False,'error':str(e)}
   checks=[report.get('range') and report.get('parse') and report.get('media'),report.get('layout'),report.get('transpose') and report.get('synth') and files['midi'],report.get('media') and report.get('synth'),files['midi'] and files['pdf']]
   logs=Path(os.environ.get('SWECLAR_LOG_DIR',temp));logs.mkdir(parents=True,exist_ok=True);(logs/'notation_observations.json').write_text(json.dumps({'browser':report,'exports':files},indent=2)+'\n')
   if os.environ.get('NOTATION_QA_OUTPUT'):
    out=Path(os.environ['NOTATION_QA_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    for f in exports.glob('*'):shutil.copy2(f,out/f.name)
   return {'harness_ok':True,'observations':{'browser':report,'exports':files},'results':[{'ru_id':f'RU-{i:03}','passed':bool(c) and not report.get('errors'),'detail':str(report.get('errors',[]))} for i,c in enumerate(checks,1)]}
  finally:
   server.terminate();server.wait(timeout=5)
   subprocess.run([sys.executable,'-I','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(q) if q.is_dir() else q.unlink()) for q in p.iterdir()]',str(work)],check=True,**identity())
if __name__=='__main__':print(json.dumps(main()))
