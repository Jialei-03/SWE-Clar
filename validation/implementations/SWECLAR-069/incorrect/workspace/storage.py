import sqlite3,json,copy
from solution import process_marketplace_action
class LedgerStore:
 def __init__(self,path):
  self.path=path
  with self.connect() as db:db.executescript("CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entries(seq INTEGER PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT,'immutable');END;CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT,'immutable');END;")
 def connect(self):return sqlite3.connect(self.path,timeout=20)
 def read(self,db):
  row=db.execute('SELECT payload FROM state WHERE id=1').fetchone()
  if not row:raise ValueError('initialize_first')
  result=json.loads(row[0]);result['ledger']=[json.loads(x[0]) for x in db.execute('SELECT payload FROM entries ORDER BY seq')];return result
 def init(self,seed):
  value=copy.deepcopy(seed);entries=value.pop('ledger',[]);value.setdefault('users',{});value.setdefault('jobs',{});value.setdefault('processed_ids',[])
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(value),))
   for entry in entries:db.execute('INSERT INTO entries(event_id,payload) VALUES(?,?)',(entry['event_id'],json.dumps(entry)))
   return self.read(db)
 def snapshot(self):
  with self.connect() as db:return self.read(db)
 def apply(self,action):
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');before=self.read(db);result=process_marketplace_action(before,action)
   if 'error' in result:return result
   ledger=result['ledger']
   if ledger[:len(before['ledger'])]!=before['ledger']:raise ValueError('ledger_changed')
   for entry in ledger[len(before['ledger']):]:db.execute('INSERT INTO entries(event_id,payload) VALUES(?,?)',(entry['event_id'],json.dumps(entry)))
   value=copy.deepcopy(result);value.pop('ledger');value.pop('result',None);value.pop('error',None);db.execute('UPDATE state SET payload=? WHERE id=1',(json.dumps(value),));return result
