"""Local operator CLI; act outputs only the action's public envelope."""
import argparse,json,sqlite3,sys

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default='coaching.sqlite');p.add_argument('command',choices=['init','show','act']);a=p.parse_args();db=sqlite3.connect(a.db)
 db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
 try:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
  if a.command=='init':
   if row is not None:raise ValueError('already_initialized')
   out=json.load(sys.stdin)
   if not isinstance(out,dict):raise ValueError('invalid_state')
   db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(out,allow_nan=False),))
  else:
   if row is None:raise ValueError('not_initialized')
   out=json.loads(row[0])
   if a.command=='act':
    action=json.load(sys.stdin)
    from solution import process_coaching_action
    out=process_coaching_action(out,action)
    if not isinstance(out,dict):raise ValueError('invalid_result')
    if 'error' not in out:db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(out,allow_nan=False),))
  db.commit()
  if a.command=='act':out={k:out[k] for k in ('result','error') if k in out}
  print(json.dumps(out,allow_nan=False))
 except (ValueError,TypeError,KeyError):
  db.rollback();print(json.dumps({'error':{'code':'invalid'}}))
 finally:db.close()
if __name__=='__main__':main()
