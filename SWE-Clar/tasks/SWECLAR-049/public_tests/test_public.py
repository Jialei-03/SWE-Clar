import json,os,sys,tempfile,subprocess,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
root=Path(os.environ.get('CANDIDATE_ROOT','/workspace'));sys.path.insert(0,str(root))
from solution import process_mentor_event
with tempfile.TemporaryDirectory() as d:
 db=d+'/public.sqlite'
 a=process_mentor_event(db,{'type':'mentor_intake','email':' M@Example.test ','name':' Mentor '})['result']
 b=process_mentor_event(db,{'type':'mentee_intake','email':'N@example.test'})['result']
 p=subprocess.Popen([sys.executable,str(root/'server.py'),'--db',db,'--port','0'],stdout=subprocess.PIPE,text=True)
 try:
  port=json.loads(p.stdout.readline())['port'];base='http://127.0.0.1:'+str(port)
  assert json.load(urllib.request.urlopen(base+'/health'))['ok']
  def post(e):
   req=urllib.request.Request(base+'/events',data=json.dumps(e).encode(),headers={'Content-Type':'application/json'})
   try:r=urllib.request.urlopen(req,timeout=10)
   except urllib.error.HTTPError as x:r=x
   with r:return r.status,json.load(r)
  with ThreadPoolExecutor(max_workers=4) as pool:r=list(pool.map(lambda _:post({'type':'create_match','mentor_id':a['profile_id'],'mentee_id':b['profile_id']}),range(6)))
  assert all(s==200 for s,o in r);mid=r[0][1]['result']['match_id'];assert all(o['result']['match_id']==mid for s,o in r)
  with ThreadPoolExecutor(max_workers=4) as pool:r=list(pool.map(lambda _:post({'type':'notify_match','match_id':mid}),range(6)))
  assert len({o['result']['notice_id'] for s,o in r})==1
  assert post({'type':'notify_match','match_id':'absent'})[0]==400
 finally:p.terminate();p.wait(timeout=5)
 print('PASS: relational intake smoke and existing concurrent matching/outbox regression')
