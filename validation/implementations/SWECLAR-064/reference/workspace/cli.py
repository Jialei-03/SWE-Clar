"""Local SQLite interface; synthetic authentication is separate from public state."""
import argparse,copy,json,sqlite3,sys

def public_state(value,secrets=()):
 if isinstance(value,dict):return {k:public_state(v,secrets) for k,v in value.items() if k not in {'phone','otp'}}
 if isinstance(value,list):return [public_state(v,secrets) for v in value]
 if isinstance(value,str):
  for secret in secrets:
   if isinstance(secret,str) and secret:value=value.replace(secret,'[private]')
 return value

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default='matchmaker.sqlite');p.add_argument('command',choices=['init','show','act']);a=p.parse_args();db=sqlite3.connect(a.db)
 db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)');db.execute('CREATE TABLE IF NOT EXISTS auth(user_id TEXT PRIMARY KEY,body TEXT NOT NULL)')
 try:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT body FROM state WHERE id=1').fetchone();auth={uid:json.loads(body) for uid,body in db.execute('SELECT user_id,body FROM auth')};secrets=[v for x in auth.values() for v in x.values()]
  if a.command=='init':
   if row is not None:raise ValueError('already_initialized')
   initial=json.load(sys.stdin)
   if not isinstance(initial,dict):raise ValueError('invalid_state')
   for uid,user in initial.get('users',{}).items():
    credentials={k:user[k] for k in ['phone','otp'] if k in user};db.execute('INSERT INTO auth VALUES(?,?)',(uid,json.dumps(credentials)));secrets.extend(credentials.values())
   out=public_state(initial,secrets);db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(out,allow_nan=False),))
  else:
   if row is None:raise ValueError('not_initialized')
   out=json.loads(row[0])
   if a.command=='act':
    command=json.load(sys.stdin)
    if not isinstance(command,dict):raise ValueError('invalid_command')
    supplied=copy.deepcopy(out)
    for uid,credentials in auth.items():
     if uid in supplied.get('users',{}):supplied['users'][uid].update(credentials)
    from solution import process_matchmaker_command
    out=process_matchmaker_command(supplied,command)
    if not isinstance(out,dict):raise ValueError('invalid_result')
    out=public_state(out,secrets)
    if 'error' not in out:db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(out,allow_nan=False),))
  db.commit();print(json.dumps(public_state(out,secrets),allow_nan=False))
 except (ValueError,TypeError,KeyError) as e:
  db.rollback();print(json.dumps({'error':{'code':'invalid'}}))
 finally:db.close()
if __name__=='__main__':main()
