from pathlib import Path
import time,os,json,sys,subprocess,select,tempfile,urllib.request,urllib.error,urllib.parse,traceback,threading,shutil,base64,io,hashlib
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
class InfrastructureError(RuntimeError):pass
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent;NODE=os.environ.get('NODE_BIN','node')
def face(n):return '00000000-0000-0000-0000-'+f'{n:012d}'
def png(color,format='PNG'):
 out=io.BytesIO();Image.new('RGB',(20,25),color).save(out,format=format);return out.getvalue()
class Provider:
 def __enter__(self):
  self.images={key:png(color) for key,color in [('one.png','blue'),('two.png','green'),('three.png','red'),('four.png','yellow'),('constructor','purple')]};self.ids={'one.png':[face(1),face(2)],'two.png':[face(3)],'three.png':[face(4)],'four.png':[face(5)],'constructor':[face(6)]};self.images['sample.jpg']=png('orange','JPEG');self.ids['sample.jpg']=[face(7)];self.scan_keys=['one.png','two.png','three.png'];self.calls=[];self.indexed={};self.fail=False;self.loop=False;outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def send(self,status,mime,data):self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   def do_GET(self):
    parsed=urllib.parse.urlsplit(self.path);query=urllib.parse.parse_qs(parsed.query);auth=self.headers.get('Authorization','');outer.calls.append(('s3',self.path,auth))
    if 'list-type' in query:
     page2='continuation-token' in query;keys=outer.scan_keys[2:] if page2 else outer.scan_keys[:2];truncated=not page2 or outer.loop;body='<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>synthetic-images</Name><IsTruncated>'+str(truncated).lower()+'</IsTruncated>'+(' <NextContinuationToken>second-page</NextContinuationToken>' if truncated else '')+''.join('<Contents><Key>'+key+'</Key></Contents>' for key in keys)+'</ListBucketResult>';return self.send(200,'application/xml',body.encode())
    key=urllib.parse.unquote(parsed.path.removeprefix('/synthetic-images/'));data=outer.images.get(key)
    if data is None:return self.send(404,'application/xml',b'<Error><Code>NoSuchKey</Code></Error>')
    self.send(200,'image/png',data)
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));target=self.headers.get('X-Amz-Target','').split('.')[-1];outer.calls.append((target,body,self.headers.get('Authorization','')))
    if outer.fail:return self.send(503,'application/x-amz-json-1.1',b'{"__type":"ServiceUnavailableException","message":"Synthetic unavailable"}')
    if target=='IndexFaces':
     raw=base64.b64decode(body.get('Image',{}).get('Bytes',''));keys=[key for key,data in outer.images.items() if raw==data]
     if len(keys)!=1:return self.send(400,'application/x-amz-json-1.1',b'{"__type":"InvalidImageFormatException"}')
     key=keys[0];outer.indexed[body['ExternalImageId']]=key;result={'FaceRecords':[{'Face':{'FaceId':ident},'FaceDetail':{'Confidence':91,'Quality':{'Brightness':13.37,'Sharpness':1.23}}} for ident in outer.ids[key]],'FaceModelVersion':'fixture'}
    elif target=='SearchFaces':
     ident=body['FaceId'];matches=[(ident,100)]
     if ident==face(3):matches.extend([(face(1),90),(face(999),99)])
     if ident==face(4):matches.append((face(2),89.999))
     if ident==face(5):matches.extend([(face(1),99),(face(2),90)])
     result={'FaceMatches':[{'Face':{'FaceId':f},'Similarity':score} for f,score in matches],'SearchedFaceId':ident}
    else:return self.send(400,'application/x-amz-json-1.1',b'{}')
    self.send(200,'application/x-amz-json-1.1',json.dumps(result).encode())
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port);return self
 def __exit__(self,*args):self.server.shutdown();self.server.server_close()
class App:
 def __init__(self,p,root,interval=60000):
  root.chmod(0o777)
  self.root=root;self.state=root/'state.json';config=root/'config.json';config.write_text(json.dumps({'bucket':'synthetic-images','collection':'synthetic-collection','s3Endpoint':p.url,'rekognitionEndpoint':p.url,'poll_interval_ms':interval,'credentials':{'accessKeyId':'synthetic-access','secretAccessKey':'synthetic-secret'}}))
  self.p=subprocess.Popen([NODE,str(ROOT/'server.cjs')],cwd=ROOT,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'NODE_PATH':os.environ['NODE_PATH'],'HOME':'/tmp','CATALOG_CONFIG':str(config),'CATALOG_STATE':str(self.state)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([self.p.stdout],[],[],8)[0]:self.close();raise AssertionError('Server startup failed')
  line=self.p.stdout.readline();assert line,self.p.stderr.read()[-1600:];self.url='http://127.0.0.1:'+str(json.loads(line)['port'])
 def close(self):
  if self.p.poll() is None:self.p.terminate();self.p.wait(timeout=5)
 def request(self,path,action=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(action).encode() if action is not None else None,headers={'Content-Type':'application/json'})
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=6) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def action(self,action):
  status,raw=self.request('/action',action);assert status==200,(status,raw);return json.loads(raw)
 def groups(self,q=''):return json.loads(self.request('/groups?q='+urllib.parse.quote(q))[1])

def ru001(a,p):
 a.action({'type':'ingest','key':'one.png','faces':[{'signature':'forged'}]});saved=read_state(a.state);assert b'synthetic-secret' not in saved and b'FaceDetail' not in saved and b'Quality' not in saved and b'forged' not in saved
 for path in ['/provider.cjs','/config.json','/state.json','/../catalog.cjs']:assert a.request(path)[0]==404
 a.close();new=App(p,a.root)
 try:assert len(new.groups())==2 and new.request('/image?key=one.png')[1]==p.images['one.png']
 finally:new.close()
 assert all('AWS4-HMAC-SHA256 ' in row[2] and 'Signature=' in row[2] for row in p.calls),p.calls

def ru002(a,p):
 a.action({'type':'scan'});index=[r for r in p.calls if r[0]=='IndexFaces'];assert len(index)==3 and len(p.indexed)==3
 assert all(r[1]['CollectionId']=='synthetic-collection' and r[1]['DetectionAttributes']==['DEFAULT'] for r in index)
 for row in index:assert base64.b64decode(row[1]['Image']['Bytes']) in p.images.values() and isinstance(row[1]['ExternalImageId'],str) and bool(row[1]['ExternalImageId'])
 assert any('continuation-token=' in r[1] for r in p.calls if r[0]=='s3')
 before=len(p.calls)
 with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:a.action({'type':'ingest','key':'one.png'}),range(6)))
 assert all(r['duplicate'] for r in results) and len(p.calls)==before
 state=read_state(a.state);p.fail=True;assert a.request('/action',{'type':'ingest','key':'four.png'})[0]==400 and read_state(a.state)==state;p.fail=False
 assert a.request('/action',{'type':'ingest','key':'missing.png'})[0]==400 and read_state(a.state)==state
 # Object names that coincide with Object.prototype properties are ordinary keys.
 a.action({'type':'ingest','key':'constructor'});assert a.request('/image?key=constructor')[1]==p.images['constructor']
 a.action({'type':'ingest','key':'sample.jpg'});assert a.request('/image?key=sample.jpg')[1]==p.images['sample.jpg']
 with urllib.request.urlopen(a.url+'/image?key=sample.jpg') as response:assert response.headers.get_content_type()=='image/jpeg'
 for invalid_ids in [[face(21),face(21)],[None]]:
  p.images['invalid-ids.png']=png('pink');p.ids['invalid-ids.png']=invalid_ids;before=read_state(a.state)
  assert a.request('/action',{'type':'ingest','key':'invalid-ids.png'})[0]==400 and read_state(a.state)==before
 p.images['empty.png']=b'';p.ids['empty.png']=[];before=read_state(a.state)
 assert a.request('/action',{'type':'ingest','key':'empty.png'})[0]==400 and read_state(a.state)==before
 p.loop=True;assert a.request('/action',{'type':'scan'})[0]==400

def ru003(a,p):
 a.action({'type':'scan'});observed=a.groups();assert len(observed)==3,observed
 by_images={frozenset(g['image_keys']):g for g in observed}
 assert set(by_images)=={frozenset(['one.png','two.png']),frozenset(['one.png']),frozenset(['three.png'])}
 groups=[by_images[frozenset(keys)] for keys in [['one.png','two.png'],['one.png'],['three.png']]]
 searches=[r for r in p.calls if r[0]=='SearchFaces'];assert len(searches)==4 and all(r[1]['CollectionId']=='synthetic-collection' for r in searches)
 a.action({'type':'label','group_id':groups[0]['group_id'],'name':'First label'});a.action({'type':'label','group_id':groups[1]['group_id'],'name':'Second label'});before=read_state(a.state);assert a.request('/action',{'type':'ingest','key':'four.png'})[0]==400 and read_state(a.state)==before
 a.action({'type':'label','group_id':groups[1]['group_id'],'name':'First label'});a.action({'type':'ingest','key':'four.png'});merged=a.groups();assert len(merged)==2
 winner=next(g for g in merged if g['group_id']==groups[0]['group_id'])
 assert winner['name']=='First label' and set(winner['image_keys'])=={'four.png','one.png','two.png'}

def ru004(a,p):
 a.action({'type':'ingest','key':'one.png'});gid=a.groups()[0]['group_id'];a.action({'type':'label','group_id':gid,'name':' Sample Group '});assert next(g for g in a.groups() if g['group_id']==gid)['name']=='Sample Group';a.action({'type':'label','group_id':gid,'name':'Renamed Group'});before=read_state(a.state)
 for ident,name in [(gid,''),('missing','Label')]:assert a.request('/action',{'type':'label','group_id':ident,'name':name})[0]==400 and read_state(a.state)==before


def ru005(a,p):
 a.action({'type':'scan'});gid=next(g['group_id'] for g in a.groups() if set(g['image_keys'])=={'one.png','two.png'});a.action({'type':'label','group_id':gid,'name':'Sample Group'});assert [g['group_id'] for g in a.groups('sAmPlE')]==[gid] and a.groups('unmatched')==[]
 for row in a.groups('sample'):
  for key in row['image_keys']:assert a.request('/image?key='+urllib.parse.quote(key))[1]==p.images[key]
 result=subprocess.run([sys.executable,'-I','/public_tests/browser_observe.py'],input=json.dumps({'url':a.url,'initial_name':'Sample Group','name':'Browser <b>Label</b>','query':'bRoWsEr'}),env={'PATH':os.environ['PATH'],'HOME':'/tmp','PLAYWRIGHT_BROWSERS_PATH':'/ms-playwright'},user=1000,group=1000,extra_groups=[],capture_output=True,text=True,timeout=30)
 if result.returncode==2:raise InfrastructureError(result.stdout)
 assert result.returncode==0,result.stderr
 data=json.loads(result.stdout);assert data['restored'] and len(data['images'])==2 and all(r['width']==20 and r['height']==25 for r in data['images']),data
 assert a.groups('browser')[0]['name']=='Browser <b>Label</b>'


def read_state(path):
 return subprocess.check_output([sys.executable,'-I','-c','from pathlib import Path;import sys;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())',str(path)],user=1000,group=1000,extra_groups=[])
def cleanup(root):
 subprocess.run([sys.executable,'-I','-c',"from pathlib import Path;import shutil,sys;[(shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()) for p in Path(sys.argv[1]).iterdir()]",str(root)],check=True,user=1000,group=1000,extra_groups=[])
def automatic_discovery():
 with tempfile.TemporaryDirectory(prefix='catalogue-poll-') as temp,Provider() as provider:
  provider.scan_keys=[]; app=App(provider,Path(temp),interval=50)
  def wait_until(predicate):
   deadline=time.monotonic()+8
   while not predicate():
    assert time.monotonic()<deadline,'Automatic discovery did not progress'
    time.sleep(.05)
  try:
   wait_until(lambda:any(r[0]=='s3' for r in provider.calls))
   assert app.groups()==[]
   provider.fail=True;provider.scan_keys=['one.png']
   wait_until(lambda:any(r[0]=='IndexFaces' for r in provider.calls))
   assert app.groups()==[]
   provider.fail=False
   wait_until(lambda:len(app.groups())==2)
   provider.scan_keys.append('three.png')
   wait_until(lambda:any('three.png' in g['image_keys'] for g in app.groups()))
  finally:app.close();cleanup(Path(temp))

def main():
 if not Path('/public_tests/browser_observe.py').is_file():return {'harness_ok':False,'error':'Missing browser observer','results':[]}
 if not shutil.which(NODE):return {'harness_ok':False,'error':'Node runtime unavailable','results':[]}
 check=subprocess.run([NODE,'-e',"require('@aws-sdk/client-s3');require('@aws-sdk/client-rekognition')"],cwd='/',env={'PATH':os.environ['PATH'],'NODE_PATH':os.environ['NODE_PATH']},user=1000,group=1000,extra_groups=[],capture_output=True,text=True)
 if check.returncode:return {'harness_ok':False,'error':'Pinned AWS SDK dependencies unavailable','results':[]}
 rows=[]
 for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
  a=None
  try:
   with tempfile.TemporaryDirectory(prefix='sweclar-catalogue-') as temp,Provider() as p:
    try:
     a=App(p,Path(temp));test(a,p)
     if i==2:automatic_discovery()
    finally:
     if a:a.close()
     cleanup(Path(temp))
   row={'ru_id':f'RU-{i:03}','passed':True}
  except (InfrastructureError,subprocess.TimeoutExpired) as e:return {'harness_ok':False,'error':str(e),'results':[]}
  except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-2200:]}
  rows.append(row)
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
