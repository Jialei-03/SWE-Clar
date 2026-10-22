import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from scheduling_support import Application
shift={'id':'shift-a','starts_at':'2030-04-03T10:00:00+00:00','location':'Synthetic hall','address':'Fixture lane','map_url':'https://maps.example.test/a','manager_email':'manager@example.test','capacity':4}
with Application(shifts=[shift]) as app:
 event={'id':'signup-a','shift_id':'shift-a','employee':{'id':'employee-a','name':'Worker A','email':'worker@example.test','phone':'+12025550101'}}
 result=app.request('/signups',event);assert result['status']=='Confirmed'
 assert app.request('/signups',event)==result
 state=app.request('/state');assert len(state['employees'])==len(state['signups'])==1
 receipts=app.fixture.receipts();assert len(receipts)==3
 assert {(r['channel'],r['recipient']) for r in receipts}=={('sms','+12025550101'),('email','worker@example.test'),('manager_email','manager@example.test')}
 assert all(all(value in r['body'] for value in ['Worker A',shift['starts_at'],shift['location'],shift['address'],shift['map_url']]) for r in receipts)
print(json.dumps({'passed':True,'public_signup_http_and_independent_receipts':True}))
