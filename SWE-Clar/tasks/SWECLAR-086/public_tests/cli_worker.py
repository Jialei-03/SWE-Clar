"""Independent pipe observer: first-stage input stays open while output is checked."""
import json,subprocess,sys,tempfile,selectors,os,time
from pathlib import Path
r=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as temp:
 fixture=Path(temp)/'places.json';fixture.write_text(json.dumps(r['places']))
 p=subprocess.Popen([sys.executable,str(Path(r['project'])/'main.py'),'--places',str(fixture),'--location',r['location']],cwd=r['project'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 early=b'';selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
 try:
  p.stdin.write(r['first'].encode());p.stdin.flush();deadline=time.monotonic()+5
  while b'\n\n' not in early and time.monotonic()<deadline:
   if selector.select(max(0,deadline-time.monotonic())):
    data=os.read(p.stdout.fileno(),65536)
    if not data:break
    early+=data
  try:p.stdin.write(r.get('rest','').encode());p.stdin.close()
  except BrokenPipeError:pass
  p.stdin=None;out,err=p.communicate(timeout=10)
  print(json.dumps({'early':early.decode(),'stdout':(early+out).decode(),'returncode':p.returncode,'stderr':err.decode()[-800:]}))
 finally:
  selector.close()
  if p.poll() is None:p.kill();p.wait()
