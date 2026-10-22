import json
from candidate_proxy import call,workflow
SLOT='2026-01-01T10:00:00Z/2026-01-01T11:00:00Z';CROSS='2026-01-01T10:30:00Z/2026-01-01T11:30:00Z';NEXT='2026-01-01T11:00:00Z/2026-01-01T12:00:00Z'
def header(headers,name):return next((v for k,v in headers.items() if k.casefold()==name.casefold()),None)
def initial():return {'users':{'student':{'role':'student'},'other':{'role':'student'},'parent':{'role':'parent','student_ids':['student']},'outsider':{'role':'parent','student_ids':['other']},'instructor':{'role':'instructor'},'unassigned':{'role':'instructor'},'admin':{'role':'admin'}},'packages':{'small':3,'large':8,'same_size':3},'credits':{'student':3,'other':2},'availability':{'instructor':[SLOT,CROSS,NEXT]},'low_credit_threshold':2}
def book(bid='b',slot=SLOT):return {'type':'book','booking_id':bid,'student_id':'student','instructor_id':'instructor','slot':slot}
def req(action,user='student'):return {'op':'request','action':action,'user':user}
def ok(row):
 status,data=row['response'];assert status==200 and 'result' in data,(status,data);return data['result']
def denied(row):assert row['response'][0]>=400 and row['response'][1].get('error')

def assert_email_payload(row,event,expected):
 # Additional provider metadata is legal; required delivery content is not optional.
 body=row['emails'][event]
 required={'event_id':event,**expected}
 assert all(body.get(k)==v for k,v in required.items()),body
 attempts=[(headers,body) for method,path,headers,*rest in row['calls'] if method=='POST' and path=='/emails' for body in rest if body.get('event_id')==event]
 assert attempts
 for headers,body in attempts:
  assert header(headers,'Idempotency-Key')==event
  assert all(body.get(k)==v for k,v in required.items()),body

def test_ru_001_auth_immutability_and_restart():
 a={'type':'set_availability','instructor_id':'instructor','slots':[SLOT],'actor_id':'instructor'};s=initial();assert call(s,a)['availability']['instructor']==[SLOT]
 ops=[req({'type':'portal'},user) for user in [None,'missing','bare']]+[req(a,'instructor'),{'op':'restart'},req({'type':'portal','actor_id':'admin','viewer_id':'admin','student_id':'student','booking_id':'missing'},'outsider')]
 rows=workflow(s,ops)
 for row in rows[:3]:assert row['response'][0]==401 and 'error' in row['response'][1]
 ok(rows[3]);assert rows[3]['state']['availability']['instructor']==[SLOT];assert rows[3]['state']==rows[4]['state'];denied(rows[5])
 assert 'synthetic-provider' not in json.dumps(rows[3]['state']) and 'sessions' not in rows[3]['state']

def test_ru_002_permissions_overlap_and_competing_bookings():
 bad=[req({'type':'set_availability','instructor_id':'instructor','slots':[slot]},'instructor') for slot in ['bad','2026-01-01T10:00:00/2026-01-01T11:00:00',NEXT.split('/')[1]+'/'+NEXT.split('/')[0]]]
 race={'op':'parallel','requests':[{'action':book('race'+str(i))} for i in range(4)]}
 rows=workflow(initial(),[req({'type':'set_availability','instructor_id':'instructor','slots':[SLOT],'actor_id':'admin'})]+bad+[race,req(book('overlap',CROSS)),req(book('adjacent',NEXT),'parent')])
 for row in rows[:4]:denied(row);assert not row['calls']
 assert sum(status==200 for status,_ in rows[4]['response'])==1 and len(rows[4]['state']['bookings'])==1 and len(rows[4]['meetings'])==1
 denied(rows[5]);ok(rows[6]);assert rows[6]['state']['credits']['student']==3
 rows=workflow(initial(),[req(book()),req({'type':'cancel','booking_id':'b'},'parent'),req(book('replacement'))]);ok(rows[1]);ok(rows[2]);assert rows[-1]['state']['credits']['student']==3

def test_ru_003_verified_receipt_catalog_and_replay():
 event='pay /1';receipt={'event_id':event,'student_id':'student','package_id':'small','paid':True,'raw_card':'PROVIDER-CARD-SECRET'};a={'type':'purchase_package','student_id':'student','payment_event_id':event,'credits':999,'paid':True,'card_number':'CALLER-CARD-SECRET'}
 rows=workflow(initial(),[{'op':'parallel','requests':[{'action':a} for _ in range(4)]},{'op':'payment','event_id':event,'receipt':{**receipt,'package_id':'same_size'}},req(a),req(a,'outsider'),{'op':'restart'}],{event:receipt})
 assert all(status==200 for status,_ in rows[0]['response']);state=rows[0]['state'];assert state['credits']['student']==6 and len(state['ledger'])==1 and state['ledger'][0]['reason']=='package_purchase'
 assert not any(secret in json.dumps(state) for secret in ['PROVIDER-CARD-SECRET','CALLER-CARD-SECRET','synthetic-provider'])
 calls=rows[0]['calls'];assert len(calls)==4 and all(c[0]=='GET' and c[1]=='/payments/pay%20%2F1' and header(c[2],'Authorization')=='Bearer synthetic-provider' for c in calls)
 denied(rows[2]);denied(rows[3]);assert rows[3]['calls']==rows[2]['calls'] and rows[4]['state']['credits']['student']==6
 for patch in [{'paid':False},{'student_id':'other'},{'event_id':'wrong'},{'package_id':'unknown'}]:
  bad=workflow(initial(),[req(a)],{event:{**receipt,**patch}});denied(bad[0]);assert bad[0]['state']['credits']['student']==3

def test_ru_004_completion_acknowledgement_retry_and_single_debit():
 complete={'type':'complete','booking_id':'b'}
 rows=workflow(initial(),[req(book()),{'op':'mode','value':'email_failure'},req(complete,'instructor'),{'op':'mode','value':'accepted_then_failure'},req(complete,'instructor'),req(complete,'instructor'),req(complete,'instructor'),req({**complete,'actor_id':'admin'},'outsider')])
 before=rows[0]['state'];denied(rows[2]);denied(rows[4]);assert rows[2]['state']==before==rows[4]['state'];ok(rows[5]);ok(rows[6]);denied(rows[7])
 state=rows[6]['state'];assert state['credits']['student']==2 and state['bookings']['b']['status']=='completed' and len(state['ledger'])==1 and state['ledger'][0]['delta']==-1 and state['ledger'][0]['reason']=='lesson_completed'
 assert rows[6]['email_attempts'].count('low_credit:b')==3 and rows[6]['emails']['low_credit:b']['balance']==2
 assert_email_payload(rows[6],'low_credit:b',{'kind':'low_credit','student_id':'student','booking_id':'b','balance':2})
 assert rows[6]['calls']==rows[5]['calls']

def test_ru_005_meeting_confirmation_retry_and_portal_scope():
 ops=[{'op':'mode','value':'meeting_failure'},req(book()),{'op':'mode','value':'wrong_ack'},req(book()),{'op':'mode','value':'accepted_then_failure'},req(book()),{'op':'mode','value':None},req(book())]
 ops += [req({'type':'portal','booking_id':'b','student_id':'student'},user) for user in ['student','parent','instructor','admin','outsider','unassigned']]
 rows=workflow(initial(),ops)
 for i in [1,3,5]:denied(rows[i]);assert not rows[i]['state'].get('bookings')
 result=ok(rows[7]);assert result['meeting_link']==rows[7]['meetings']['meeting:b']['join_url'] and len(rows[7]['meetings'])==len(rows[7]['emails'])==1
 assert_email_payload(rows[7],'confirmation:b',{'kind':'booking_confirmation','booking_id':'b','student_id':'student','meeting_link':rows[7]['meetings']['meeting:b']['join_url']})
 for row in rows[8:12]:
  value=ok(row);assert all(k in value for k in ['booking_id','status','meeting_link','credit_balance']);assert not set(value)&{'users','ledger','sessions','provider_token','state'} and 'synthetic-provider' not in json.dumps(value)
 for row in rows[12:]:denied(row)
 assert len(rows[11]['state']['audit'])==2
 for method,path,headers,*body in rows[7]['calls']:
  if method=='POST':assert header(headers,'Authorization')=='Bearer synthetic-provider' and header(headers,'Idempotency-Key') in ['meeting:b','confirmation:b']
