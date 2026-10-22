import json,sys,traceback,tempfile,urllib.request
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,'/public_tests')
from scheduling_support import Application

def shift(id='a',manager='one@example.test',stamp='2030-04-03T10:00:00+00:00',capacity=3):
 return dict(id=id,starts_at=stamp,location='Synthetic '+id,address='Fixture lane '+id,map_url='https://maps.example.test/'+id,manager_email=manager,capacity=capacity)
def event(id='a',sid='a',email='worker@example.test'):
 return {'id':'signup-'+id,'shift_id':sid,'employee':{'id':'worker-'+id,'name':'Worker '+id,'email':email,'phone':'+12025550101'}}
def state(app):return app.request('/state')
def send(app,e=None):return app.request('/signups',e or event())
def tick(app,now):return app.request('/tick',{'now':now})

def timezone_policy(gate):
 from datetime import datetime,timedelta,timezone
 from zoneinfo import ZoneInfo
 # Spring DST transition plus a zone whose calendar date leads UTC.
 for zone,day in [('Asia/Tokyo','2030-04-03'),('America/New_York','2030-03-10')]:
  local=datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone))
  utc=lambda value:value.astimezone(timezone.utc).isoformat()
  if gate==4:
   start=local+timedelta(hours=10)
   with Application(shifts=[shift(stamp=utc(start))],timezone=zone) as app:
    send(app)
    tick(app,utc(local-timedelta(days=1,seconds=1)))
    assert state(app)['signups'][0]['status']=='Confirmed','Not yet the preceding local date'
    tick(app,utc(local-timedelta(days=1)))
    assert state(app)['signups'][0]['status']=='Reminder Sent 24h','Local midnight enters reminder date'
  if gate==5:
   with Application(shifts=[shift(stamp=utc(local+timedelta(hours=10)))],timezone=zone) as app:
    tick(app,utc(local+timedelta(hours=6)-timedelta(seconds=1)))
    assert app.fixture.receipts()==[],'No roster before local 06:00'
    tick(app,utc(local+timedelta(hours=6)))
    messages=app.fixture.receipts();assert len(messages)==1
    assert messages[0]['recipient']=='one@example.test'
    assert json.loads(messages[0]['body'])==[dict(shift_id='a',starts_at=utc(local+timedelta(hours=10)),location='Synthetic a',total=3,filled=0,remaining=3)]
    tick(app,utc(local+timedelta(hours=7)));assert app.fixture.receipts()==messages

def run(gate):
 if gate in (4,5):timezone_policy(gate)
 shifts=[shift(),shift('b','two@example.test'),shift('c','one@example.test',capacity=1)]
 with Application(shifts=shifts) as app:
  if gate==1:
   send(app);send(app,event('b','b'));s=state(app)
   assert len(s['employees'])==1 and len(s['signups'])==2
   assert {r['shift_id'] for r in s['signups']}=={'a','b'}
   assert len({r['employee_id'] for r in s['signups']})==1
   assert len(s['shifts'])==3
  elif gate==2:
   send(app);r=app.fixture.receipts();assert len(r)==3
   assert {(x['channel'],x['recipient']) for x in r}=={('sms','+12025550101'),('email','worker@example.test'),('manager_email','one@example.test')}
   assert all(all(v in x['body'] for v in ['Worker a',shifts[0]['starts_at'],shifts[0]['location'],shifts[0]['address'],shifts[0]['map_url']]) for x in r)
  elif gate==3:
   app.fixture.fail_next('email')
   try:send(app)
   except HTTPError as error:assert error.code==503
   else:raise AssertionError('Delivery failure must be reported')
   assert not any(x['status']=='Confirmed' for x in state(app)['signups'])
   send(app);send(app);assert len(app.fixture.receipts())==3
   assert len(state(app)['signups'])==1 and state(app)['signups'][0]['status']=='Confirmed'
  elif gate==4:
   send(app);tick(app,'2030-04-02T06:00:00+00:00');r=app.fixture.receipts();assert len(r)==5
   assert state(app)['signups'][0]['status']=='Reminder Sent 24h'
   tick(app,'2030-04-02T06:00:00+00:00');assert len(app.fixture.receipts())==5
   tick(app,'2030-04-03T07:59:59+00:00');count=len(app.fixture.receipts());assert state(app)['signups'][0]['status']=='Reminder Sent 24h'
   tick(app,'2030-04-03T08:00:00+00:00');assert len(app.fixture.receipts())==count+2
   assert state(app)['signups'][0]['status']=='Reminder Sent 2h'
   tick(app,'2030-04-03T10:01:00+00:00');assert len(app.fixture.receipts())==count+2
  elif gate==5:
   send(app,event('c','c'));tick(app,'2030-04-03T05:59:59+00:00');r=app.fixture.receipts();assert len(r)==4
   assert next(x for x in state(app)['shifts'] if x['id']=='c')['status']=='Full'
   tick(app,'2030-04-03T06:00:00+00:00');new=[x for x in app.fixture.receipts() if x['id'] not in {r['id'] for r in r}];assert len(new)==2
   for message in new:
    roster=json.loads(message['body']);ids={x['shift_id'] for x in roster}
    assert ids==({'a','c'} if message['recipient']=='one@example.test' else {'b'})
    for row in roster:assert row['total']==(1 if row['shift_id']=='c' else 3) and row['filled']==(1 if row['shift_id']=='c' else 0) and row['remaining']==row['total']-row['filled']
   count=len(app.fixture.receipts());tick(app,'2030-04-03T06:01:00+00:00');assert len(app.fixture.receipts())==count
  elif gate==6:
   send(app);send(app);assert all(not x['checked_in'] for x in state(app)['signups'])

def infrastructure_check():
 from notification_fixture import NotificationFixture
 with tempfile.TemporaryDirectory(prefix='schedule-health-') as folder:
  fixture=NotificationFixture(Path(folder)/'receipts.sqlite').start()
  try:
   payload={'id':'health-only','channel':'email','recipient':'health@example.test','body':'Synthetic health check'}
   req=urllib.request.Request(fixture.url+'/messages',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as response:assert response.status==200
   assert fixture.receipts()==[payload]
  finally:fixture.close()

def main():
 try:infrastructure_check()
 except Exception as error:return {'harness_ok':False,'results':[],'infrastructure_errors':[type(error).__name__+': '+str(error)]}
 results=[]
 for gate in range(1,7):
  try:run(gate);results.append({'ru_id':f'RU-{gate:03d}','passed':True})
  except Exception as error:results.append({'ru_id':f'RU-{gate:03d}','passed':False,'detail':str(error) or type(error).__name__,'trace':traceback.format_exc()[-1800:]})
 return {'harness_ok':True,'results':results}
if __name__=='__main__':print(json.dumps(main()))
