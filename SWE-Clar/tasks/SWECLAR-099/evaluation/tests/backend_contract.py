"""Protected HTTP assertions for the Linux browser photo component."""
import base64,hashlib,io,json,time,urllib.request,urllib.error,sys
sys.path.insert(0,'/public_tests')
from photo_fixtures import jpeg
from PIL import Image

def evaluate_backend(base,restart):
 origin=[base];tokens={};results={};evidence={};opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def request(user,path,body=None):
  headers={'Authorization':'Bearer '+tokens.get(user,''),'Content-Type':'application/json'}
  req=urllib.request.Request(origin[0]+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
  try:
   with opener.open(req,timeout=15) as response:
    raw=response.read();return response.status,json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw
  except urllib.error.HTTPError as error:return error.code,json.loads(error.read())
 def ok(user,path,body=None):
  status,result=request(user,path,body);assert 200<=status<300,(path,status,result);return result
 def rejected(user,path,body=None):
  status,result=request(user,path,body);assert status>=400 and isinstance(result.get('error'),str) and result['error'];return result
 for user in ['user-a','user-b','user-c','user-d','user-e']:
  status,data=request(user,'/login',{'user':user,'password':'synthetic-passphrase'});assert status==200;tokens[user]=data['token']
 make=lambda id,mode='ask':ok('user-a','/requests',{'id':id,'room':'room-one','mode':mode,'caption':'Independent color card'})
 # Start the real 60-second deadline before other checks, without forged timestamps.
 late=make('backend-late');ok('user-b','/open',{'request':late['id']})
 photo=None
 def ru2():
  ask=make('backend-ask');challenge=make('backend-challenge','challenge');duo=make('backend-duo','duo')
  assert set(ask['targets'])==set(challenge['targets'])=={'user-b','user-c','user-d'}
  assert set(duo['targets'])=={'user-a','user-b','user-c','user-d'}
  ok('user-a','/open',{'request':duo['id']});rejected('user-a','/open',{'request':ask['id']})
  replay=make('backend-duo','duo');assert replay['id']==duo['id']
  rows=ok('user-b','/requests?room=room-one');assert sum(r['id']==duo['id'] for r in rows)==1
  rejected('user-a','/requests',{'id':duo['id'],'room':'room-one','mode':'ask'})
  rejected('user-e','/requests',{'id':'outside','room':'room-one','mode':'duo'})
 def ru3():
  nonlocal photo
  row=make('backend-image');payload={'request':row['id'],'image':base64.b64encode(jpeg()).decode(),'elapsed':-900,'created':0}
  rejected('user-b','/respond',payload);opened=ok('user-b','/open',{'request':row['id']});assert opened['countdown']==3
  rejected('user-b','/respond',payload);time.sleep(3.15)
  before=time.time();photo=ok('user-b','/respond',payload);after=time.time()
  assert photo['caption']=='Independent color card' and photo['eligible']==1
  assert before-row['created']-.15<=photo['elapsed']<=after-row['created']+.15
  image=ok('user-b',photo['url']);decoded=Image.open(io.BytesIO(image));assert decoded.size==(96,80) and not dict(decoded.getexif())
  for point,color in [((20,30),(220,35,20)),((80,30),(15,35,220))]:assert max(abs(a-b) for a,b in zip(decoded.convert('RGB').getpixel(point),color))<35
  replay=ok('user-b','/respond',payload);assert replay['id']==photo['id']
  assert sum(r['id']==photo['id'] for r in ok('user-b','/timeline?room=room-one'))==1
  evidence['image_sha256']=hashlib.sha256(image).hexdigest();evidence['photo']=photo
  remaining=late['created']+60.35-time.time();assert remaining<65
  if remaining>0:time.sleep(remaining)
  latephoto=ok('user-b','/respond',{'request':late['id'],'image':payload['image'],'elapsed':0})
  assert latephoto['elapsed']>60 and latephoto['eligible']==0
  assert any(r['id']==latephoto['id'] for r in ok('user-b','/timeline?room=room-one'))
  evidence['late_photo']=latephoto
 def stored_photo():
  if photo is not None:return photo
  rows=ok('user-b','/timeline?room=room-one')
  return next(row for row in rows if row['request']=='backend-image')
 def ru4():
  route=ok('user-b','/route?room=room-one&request=backend-image');assert route['room']=='room-one' and route['request']=='backend-image'
  rejected('user-b','/route?room=room-two&request=backend-image');rejected('user-e','/route?room=room-one&request=backend-image');rejected('user-b','/route?room=room-one&request=absent')
  rejected('user-e',stored_photo()['url'])
 def ru5():
  added=ok('user-b','/contact',{'numbers':['+1 (202) 555-0100','0012025550100']});assert added['action']=='added' and set(added['users'])=={'user-a'}
  ok('user-b','/contact',{'numbers':['+12025550100']});assert ok('user-b','/contacts')==['user-a']
  invite=ok('user-b','/contact',{'numbers':['+12025550199']});assert invite['action']=='invite' and invite['numbers']==['+12025550199'];assert ok('user-b','/contacts')==['user-a']
 def ru1():
  assert restart is not None,'Real restart proof unavailable'
  persisted=stored_photo()
  image=ok('user-b',persisted['url']);prior=ok('user-b','/timeline?room=room-one')
  next_base=restart()
  if next_base:origin[0]=next_base
  after=ok('user-b','/timeline?room=room-one');assert {r['id'] for r in prior}=={r['id'] for r in after}
  assert ok('user-b',persisted['url'])==image;assert any(r['id']=='backend-image' for r in ok('user-b','/requests?room=room-one'));evidence['restart_verified']=True
 for i,check in [(2,ru2),(3,ru3),(4,ru4),(5,ru5),(1,ru1)]:
  try:check();results[str(i)]={'passed':True}
  except Exception as error:results[str(i)]={'passed':False,'detail':type(error).__name__+': '+str(error)}
 return {'results':results,'evidence':evidence,'actual_elapsed_seconds':time.time()-late['created']}
