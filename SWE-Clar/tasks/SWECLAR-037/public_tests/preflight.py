"""Protected preparation of media assets and delivery service."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Benchmark management identity required')
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'));public=Path(__file__).resolve().parent
private=Path(tempfile.mkdtemp(prefix='video-receiver-'));private.chmod(0o700)
log=(private/'receiver.log').open('w');process=subprocess.Popen([sys.executable,'-I',str(public/'receiver.py'),str(private)],stdout=log,stderr=log,start_new_session=True)
try:
 for _ in range(100):
  if (private/'ready.json').exists():break
  if process.poll() is not None:raise RuntimeError('Delivery adapter failed')
  time.sleep(.1)
 else:raise RuntimeError('Delivery adapter readiness timed out')
 url=json.loads((private/'ready.json').read_text())['url']
 subprocess.run([sys.executable,'-I',str(public/'generate_samples.py'),str(root/'runtime')],user=1000,group=1000,extra_groups=[],check=True,capture_output=True,text=True)
 script=r"""import json,sys
from pathlib import Path
root=Path(sys.argv[1]);url=sys.argv[2];runtime=root/'runtime'
request={'detection_video':str(runtime/'detection.mp4'),'recording_video':str(runtime/'recording.mp4'),'output_dir':str(runtime/'clips'),'line_x':48,'delivery_url':url}
(runtime/'request.json').write_text(json.dumps(request));(runtime/'receiver.json').write_text(json.dumps({'url':url}))
exclude=root/'.git/info/exclude'
if exclude.parent.exists():
 old=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in old.splitlines():exclude.write_text(old+'\n/runtime/\n')
"""
 subprocess.run([sys.executable,'-I','-c',script,str(root),url],user=1000,group=1000,extra_groups=[],check=True)
 print(json.dumps({'passed':True,'synthetic_videos':3,'delivery_adapter_ready':True,'request':'runtime/request.json','prepared_before_budget':True}))
except BaseException:
 process.terminate();process.wait(timeout=10);raise
finally:log.close()
