"""Five retained RU checks using public HTTP, real browser actions and restart persistence."""
import json,os,tempfile,subprocess,urllib.request,urllib.error,traceback,hashlib,shutil,sys,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
TESTS=Path(__file__).resolve().parent
PUBLIC=Path('/public_tests')
sys.path.insert(0,str(PUBLIC))
from inspection_support import Application,identity
NODE=os.environ.get('NODE_BIN','/usr/local/lib/python3.12/dist-packages/playwright/driver/node')
CONFIG={'communities':{'Community A':['Street A1','Street A2'],'Community B':['Street B1'],'Community C':['Street C1']},'access_codes':{'synthetic-admin':'admin','synthetic-inspector':'inspector','synthetic-office':'office'},'inspections':[{'id':'seed-open','community':'Community A','street':'Street A1','residence':'Sample unit 1','status':'open'},{'id':'seed-closed','community':'Community A','street':'Street A2','residence':'Sample unit 2','status':'closed'},{'id':'seed-other','community':'Community B','street':'Street B1','residence':'Sample unit 3','status':'open'}]}
class App(Application):
 def __init__(self):super().__init__(config=CONFIG)
 def request(self,command=None,role='admin'):
  headers={'Authorization':'Bearer synthetic-'+role,'Content-Type':'application/json'}
  if role=='bare':headers['Authorization']='synthetic-admin'
  req=urllib.request.Request(self.url+('/api/command' if command is not None else '/api/context'),data=json.dumps(command).encode() if command is not None else None,headers=headers)
  try:r=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10)
  except urllib.error.HTTPError as e:r=e
  with r:return r.status,json.load(r)
 def rows(self):
  status,data=self.request();assert status==200,data
  fields=['id','community','street','residence','status']
  return sorted([tuple(row[k] for k in fields) for row in data['inspections']])
 def browser(self,mode):
  env={**os.environ,'INSPECTION_PROBE_MODE':mode,'INSPECTION_BROWSER_WRAPPER':str(PUBLIC/'browser_launch.py'),'INSPECTION_BROWSER_HOME':str(self.project/'runtime')}
  r=subprocess.run([NODE,str(TESTS/'inspection_probe.cjs'),self.url],env=env,text=True,capture_output=True,timeout=30)
  assert r.returncode==0,r.stderr[-1600:]
  return json.loads(r.stdout)

def error_response(response,expected_status=None):
 status,value=response
 assert (status==expected_status if expected_status else status>=400),response
 assert isinstance(value.get('error',{}).get('code'),str) and value['error']['code'],response
 return value['error']['code']

def report_result(a,community,role='admin'):
 status,value=a.request({'type':'report','community':community},role);assert status==200,value
 result=value['result'];return {'total':result['total'],'by_status':{k:result['by_status'][k] for k in ['open','closed']}}

def create(ident='new'):return {'type':'create','id':ident,'community':'Community A','street':'Street A1','residence':'Sample unit 4'}

def summary_counts(text):
 import re
 tokens=re.findall(r'\b(?:total|open|closed|\d+)\b',text.lower())
 # Read label/value cards in either order, or a table's header then data row.
 for pairs in (list(zip(tokens[::2],tokens[1::2])),list(zip(tokens[1::2],tokens[::2])),list(zip(tokens[:3],tokens[3:]))):
  if len(tokens)==6 and {k for k,v in pairs}=={'total','open','closed'} and all(v.isdecimal() for k,v in pairs):
   return {k:int(v) for k,v in pairs}
 return None
def ru001(a):
 r=a.browser('select');assert r['first']==['Street A1','Street A2'] and r['second']==['Street B1'],r
 before=a.rows();status,result=a.request({**create(),'street':'Street B1'});error_response((status,result));assert a.rows()==before

def ru002(a):
 original=subprocess.check_output([sys.executable,'-I','-c','import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',str(a.config_file)],**identity());r=a.browser('create');assert r['created'] and r['persisted'],r
 assert any(row[0]=='browser-created' and row[4]=='open' for row in a.rows())
 with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:a.request(create('concurrent'),'inspector'),range(6)))
 assert sum(status==200 for status,_ in results)==1,results
 before=a.rows();a.stop();a.start();assert a.rows()==before and subprocess.check_output([sys.executable,'-I','-c','import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',str(a.config_file)],**identity())==original

def ru003(a):
 before=a.rows();status,result=a.request({'type':'delete','id':'seed-open','role':'admin'},'inspector');error_response((status,result));assert a.rows()==before
 error_response(a.request({'type':'delete','id':'seed-open'},'office'))
 error_response(a.request({'type':'delete','id':'seed-closed'}));assert a.rows()==before
 r=a.browser('delete');assert r['deleted'],r;assert a.rows()==[row for row in before if row[0]!='seed-open']

def ru004(a):
 before=a.rows();assert report_result(a,'Community A')=={'total':2,'by_status':{'open':1,'closed':1}}
 assert report_result(a,'Community B','office')=={'total':1,'by_status':{'open':1,'closed':0}}
 r=a.browser('report');assert summary_counts(r['summary'])=={'total':1,'open':1,'closed':0} and a.rows()==before,r
 assert report_result(a,'Community C')=={'total':0,'by_status':{'open':0,'closed':0}}

def ru005(a):
 before=a.rows()
 for role in ['missing','bare']:error_response(a.request(role=role),401)
 cases=[{**create(),'id':'seed-open'},{**create(),'id':' '},{**create(),'residence':' '},{**create(),'community':'unknown'},{'type':'delete','id':'missing'},{'type':'report','community':'missing'},{'type':'unknown'}]
 for command in cases:
  status,r=a.request(command);code=error_response((status,r));assert a.rows()==before,(command,r)
  if command['type']=='unknown':assert code=='unknown_command',(command,r)
 error_response(a.request(create(),'office'));assert a.rows()==before
 status,r=a.request();assert status==200 and 'access_codes' not in r and 'synthetic-admin' not in json.dumps(r)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--gates',default='1,2,3,4,5');args=parser.parse_args()
 selected=[int(x) for x in args.gates.split(',')];assert selected and all(1<=i<=5 for i in selected)
 if not shutil.which('php') or not Path(NODE).is_file():return {'harness_ok':False,'infrastructure_errors':['Missing prepared PHP/browser driver'],'results':[]}
 rows=[]
 for i in selected:
  try:
   with App() as app:globals()[f'ru{i:03d}'](app)
   row={'ru_id':f'RU-{i:03d}','passed':True}
  except Exception as e:row={'ru_id':f'RU-{i:03d}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-1800:]}
  rows.append(row)
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
