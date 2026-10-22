import hashlib,json,os,subprocess,tempfile
from pathlib import Path
if os.getuid()==0:
 r=subprocess.run([__import__('sys').executable,'-I',__file__],capture_output=True,text=True,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'});print(r.stdout,end='');print(r.stderr,end='',file=__import__('sys').stderr);raise SystemExit(r.returncode)
assert os.getuid()==1000
assert hashlib.sha256(Path('/opt/sweclar/ggml-tiny.en.bin').read_bytes()).hexdigest()=='921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f'
with tempfile.TemporaryDirectory() as temp:
 out=Path(temp)/'speech';r=subprocess.run(['/opt/sweclar/whisper-cli','-m','/opt/sweclar/ggml-tiny.en.bin','-f','/opt/sweclar/speech/lesson.wav','-t','2','-l','en','-otxt','-of',str(out)],text=True,capture_output=True,timeout=90);assert r.returncode==0,r.stderr
 text=out.with_suffix('.txt').read_text().strip();assert all(w in text.lower() for w in ['triangle','three','sides']),text
print(json.dumps({'passed':True,'python':__import__('sys').version.split()[0],'actual_audio_transcription':text,'uid':os.getuid(),'model_bytes':77704715}))
