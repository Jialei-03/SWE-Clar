import json,urllib.request
from store import connect

def signup(db_path,sink_url,event):
 with connect(db_path) as db:
  shift=db.execute('SELECT * FROM shifts WHERE id=?',(event['shift_id'],)).fetchone()
  if not shift:raise ValueError('unknown_shift')
  db.execute('BEGIN IMMEDIATE')
  e=event['employee'];existing=db.execute('SELECT id FROM employees WHERE email=?',(e['email'],)).fetchone()
  eid=existing['id'] if existing else e['id']
  if not existing:db.execute('INSERT INTO employees VALUES(?,?,?,?)',(eid,e['name'],e['email'],e['phone']))
  db.execute('INSERT OR IGNORE INTO signups(id,employee_id,shift_id) VALUES(?,?,?)',(event['id'],eid,shift['id']))
  current=db.execute('SELECT * FROM signups WHERE id=?',(event['id'],)).fetchone()
  if not current or current['employee_id']!=eid or current['shift_id']!=shift['id']:raise ValueError('signup_conflict')
  worker=db.execute('SELECT * FROM employees WHERE id=?',(eid,)).fetchone()
  body=f"{worker['name']} | {shift['starts_at']} | {shift['location']} | {shift['address']} | {shift['map_url']}"
  for channel,recipient in [('sms',worker['phone']),('email',worker['email']),('manager_email',shift['manager_email'])]:
   key=f"signup:{event['id']}:{channel}"
   deliver(db,sink_url,key,event['id'],channel,recipient,body)
  db.execute("UPDATE signups SET status='Confirmed' WHERE id=? AND status='New'",(event['id'],))
  return dict(db.execute('SELECT * FROM signups WHERE id=?',(event['id'],)).fetchone())

def deliver(db,sink_url,key,subject,channel,recipient,body):
 if db.execute('SELECT 1 FROM deliveries WHERE id=?',(key,)).fetchone():return
 data={'id':key,'channel':channel,'recipient':recipient,'body':body}
 req=urllib.request.Request(sink_url+'/messages',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=3) as response:
  if response.status!=200:raise RuntimeError('delivery_failed')
 db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',(key,subject,channel,recipient,body))

def tick(db_path,sink_url,now,timezone='UTC'):
 # TODO: Implement scheduled reminders and manager notifications.
 return {'processed':False}
