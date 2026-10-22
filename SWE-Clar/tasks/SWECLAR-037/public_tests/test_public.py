"""Public checks for preserved decoding, empty pipeline and real byte delivery."""
from pathlib import Path
import hashlib,json,subprocess,sys,tempfile,urllib.request
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd();sys.path.insert(0,str(root))
import pipeline
rows=pipeline.observations(root/'runtime/detection.mp4',48)
assert len(rows)==40 and sum(r['goal_candidate'] for r in rows)==2
with tempfile.TemporaryDirectory(prefix='public-video-') as tmp:
 request=json.loads((root/'runtime/request.json').read_text());request['detection_video']=str(root/'runtime/neutral.mp4');request['output_dir']=str(Path(tmp)/'output')
 f=Path(tmp)/'request.json';f.write_text(json.dumps(request))
 run=subprocess.run([sys.executable,str(root/'cli.py'),str(f)],cwd=root,text=True,capture_output=True,timeout=25)
 assert run.returncode==0,run.stderr
 assert json.loads(run.stdout)['clips']==[]
 data=(root/'runtime/recording.mp4').read_bytes();digest=hashlib.sha256(data).hexdigest()
 req=urllib.request.Request(request['delivery_url'],data=data,headers={'Content-Type':'video/mp4','X-Content-SHA256':digest,'X-Clip-ID':'public-smoke'},method='POST')
 with urllib.request.urlopen(req,timeout=3) as response:
  ack=json.load(response);assert ack['accepted'] is True and ack['sha256']==digest
print(json.dumps({'passed':True,'actual_decode':True,'empty_cli_pipeline':True,'prepared_adapter_byte_delivery':True}))
