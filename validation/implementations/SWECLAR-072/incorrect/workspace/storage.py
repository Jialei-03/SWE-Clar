import sqlite3,json,copy
from solution import process_backend_command
TRANSIENT={'error','refund_result','comment_result','login_result'}
class CommandStore:
 def __init__(self,path):
  self.path=path
  with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
 def connect(self):return sqlite3.connect(self.path,timeout=20)
 def read(self,db):
  row=db.execute('SELECT payload FROM state WHERE id=1').fetchone()
  if not row:raise ValueError('initialize_first')
  return json.loads(row[0])
 def init(self,seed):
  # Command views and errors are responses, not durable state.  Strip them
  # even when an initial seed happens to contain one.
  durable={k:v for k,v in seed.items() if k not in TRANSIENT}
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(durable,allow_nan=False),))
   return self.read(db)
 def snapshot(self):
  with self.connect() as db:return self.read(db)
 def apply(self,command):
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');out=process_backend_command(self.read(db),command)
   if 'error' not in out:db.execute('UPDATE state SET payload=? WHERE id=1',(json.dumps({k:v for k,v in out.items() if k not in TRANSIENT},allow_nan=False),))
   return out
