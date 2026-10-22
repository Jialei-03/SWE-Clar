"""Protected test-side proxy; candidate modules never load in this process."""
import json,os,select,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace

def load_solution():
 root=Path(os.environ.get('SWECLAR_SOLUTION_PATH',str(Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))/'solution.py'))).resolve().parent
 public=Path('/public_tests') if Path('/public_tests').is_dir() else Path(__file__).resolve().parents[2]/'public_tests'
 worker=public/'invoke.py'
 if not worker.is_file():raise RuntimeError('Missing benchmark invocation helper')
 def call(state,action,fetch_text=None):
  if os.geteuid()!=0:raise RuntimeError('Protected evaluator requires benchmark management identity')
  p=subprocess.Popen([sys.executable,'-I',str(worker)],cwd=root,env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1','HOME':'/tmp'},user=1000,group=1000,extra_groups=[],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
  try:
   p.stdin.write(json.dumps({'project':str(root),'state':state,'action':action,'adapter':fetch_text is not None})+'\n');p.stdin.flush()
   deadline=time.monotonic()+15
   while True:
    remaining=deadline-time.monotonic()
    if remaining<=0 or not select.select([p.stdout],[],[],remaining)[0]:raise TimeoutError('Candidate invocation timed out')
    line=p.stdout.readline()
    if not line:raise RuntimeError('Candidate invocation exited without a result')
    message=json.loads(line)
    if message['kind']=='fetch':
     if fetch_text is None:raise AssertionError('Unexpected callback without adapter')
     try:response={'text':fetch_text(message['url'])}
     except Exception as e:response={'error':str(e)}
     p.stdin.write(json.dumps(response)+'\n');p.stdin.flush()
    elif message['kind']=='result':
     assert message['state_after']==state and message['action_after']==action,'Candidate mutated caller-owned input'
     return message['value']
    elif message['kind']=='exception':raise RuntimeError(message['error'])
    else:raise AssertionError('Invalid candidate transport response')
  finally:
   if p.poll() is None:p.terminate()
   try:p.wait(timeout=3)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
 return SimpleNamespace(process_exhibition_action=call)
