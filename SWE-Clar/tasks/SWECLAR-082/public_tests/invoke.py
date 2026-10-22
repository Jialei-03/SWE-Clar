"""Generic ordinary-user classroom action runner; no hidden assertions."""
import contextlib,importlib.util,json,sys,tempfile,shutil,wave
from pathlib import Path
r=json.load(sys.stdin);wire=sys.stdout
try:
 with contextlib.redirect_stdout(sys.stderr),tempfile.TemporaryDirectory() as temp:
  root=Path(r['project']);sys.path.insert(0,str(root));assets=Path(temp)/'assets';shutil.copytree('/opt/sweclar/speech',assets)
  with wave.open(str(assets/'silent.wav'),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(32000))
  (assets/'malformed.wav').write_bytes(b'not-wave');shutil.copy2(assets/'lesson.wav',Path(temp)/'outside.wav')
  from solution import process_class_action
  from transcriber import LocalWhisper
  from translation_client import TranslationClient
  transcriber=LocalWhisper(r.get('binary','/opt/sweclar/whisper-cli'),'/opt/sweclar/ggml-tiny.en.bin',assets);translator=TranslationClient(r['url']) if r.get('url') else None
  result=process_class_action(r['state'],r['action'],transcriber,translator)
 wire.write(json.dumps({'result':result,'after':[r['state'],r['action']]})+'\n')
except Exception as e:wire.write(json.dumps({'error':type(e).__name__+': '+str(e)})+'\n')
