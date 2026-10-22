"""Local transactional interface for the pizzeria policy module."""
import argparse,json,sqlite3,sys

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',default='pizzeria.sqlite');parser.add_argument('command',choices=['init','show','act']);args=parser.parse_args()
 db=sqlite3.connect(args.db);db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
 try:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
  if args.command=='show':
   if row is None:raise ValueError('not_initialized')
   out=json.loads(row[0])
  elif args.command=='init':
   if row is not None:raise ValueError('already_initialized')
   out=json.load(sys.stdin)
   if not isinstance(out,dict):raise ValueError('invalid_state')
   db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(out,allow_nan=False),))
  else:
   if row is None:raise ValueError('not_initialized')
   action=json.load(sys.stdin)
   if not isinstance(action,dict):raise ValueError('invalid_action')
   from solution import process_pizzeria_action
   out=process_pizzeria_action(json.loads(row[0]),action)
   if not isinstance(out,dict):raise ValueError('invalid_result')
   encoded=json.dumps(out,allow_nan=False)
   if 'error' not in out:db.execute('UPDATE state SET body=? WHERE id=1',(encoded,))
  db.commit();print(json.dumps(out,allow_nan=False))
 except (ValueError,TypeError,KeyError) as e:
  db.rollback();print(json.dumps({'error':{'code':str(e) or 'invalid'}}))
 finally:db.close()
if __name__=='__main__':main()
