from candidate_proxy import observe

def req(method,path,body=None,key=None):
 x={'method':method,'path':path}
 if body is not None:x['body']=body
 if key:x['headers']={'Idempotency-Key':key}
 return x
def create(ident='t',amount=12.5,typ='normal',key=None):return req('POST','/transactions',{'transaction_id':ident,'amount':amount,'type':typ},key)
def note(ident='t',nid='n',text='Synthetic note',key=None):return req('POST','/transactions/'+ident+'/notes',{'note_id':nid,'text':text},key)
def get(ident='t'):return req('GET','/transactions/'+ident)
def fields(actual,expected):assert all(actual.get(k)==v for k,v in expected.items()),(actual,expected)
def err(row,status):assert row['status']==status and isinstance(row['body'],dict) and row['body'].get('error'),row
def records(rows):return [{k:r[k] for k in ['note_id','text','active']} for r in rows]
def stored_notes(ident='t'):return {'op':'sql','sql':'SELECT note_id,text,active FROM notes WHERE transaction_id=? ORDER BY seq','params':[ident]}
def note_rows(row):return [dict(zip(['note_id','text','active'],values)) for values in row['rows']]

def test_ru_001_real_http_storage_foundation():
 rows=observe([req('GET','/health'),req('DELETE','/unsupported'),{'method':'POST','path':'/transactions','raw':'{'},{'op':'database'},{'op':'restart'},req('GET','/health')])
 assert rows[0]['status']==rows[5]['status']==200 and rows[0]['body'].get('ok') is True
 err(rows[1],404);assert rows[1]['body']['error']=='route_not_found';err(rows[2],400);assert rows[3]['sqlite']

def test_ru_002_create_validation_conflicts_and_concurrency():
 bad=[{'transaction_id':'','amount':1,'type':'x'},{'transaction_id':'bad','amount':True,'type':'x'},{'transaction_id':'bad','amount':'1','type':'x'},{'transaction_id':'bad','amount':1,'type':'  '},{'transaction_id':'bad','amount':float('inf'),'type':'x'}]
 # Read the declared SQLite schema to isolate creation from hidden GET semantics.
 def stored(ident):return {'op':'sql','sql':'SELECT id,amount,type FROM transactions WHERE id=?','params':[ident]}
 ops=[create(),create(amount=99),stored('t')]+[req('POST','/transactions',x) for x in bad]+[stored('bad'),{'op':'parallel','requests':[create('race',amount=i) for i in range(5)]},stored('race'),create('zero',amount=0),create('negative',amount=-1.25)]
 rows=observe(ops);assert rows[0]['status']==201;fields(rows[0]['body'],{'transaction_id':'t','amount':12.5,'type':'normal','notes':[]});err(rows[1],409);assert rows[2]['rows']==[['t',12.5,'normal']]
 for row in rows[3:8]:err(row,400)
 assert rows[8]['rows']==[];assert sorted(x['status'] for x in rows[9])==[201,409,409,409,409]
 winner=next(x['body']['amount'] for x in rows[9] if x['status']==201);assert rows[10]['rows']==[['race',winner,'normal']]
 assert rows[11]['status']==rows[12]['status']==201

def test_ru_003_notes_scope_validation_order_persistence():
 rows=observe([create(),create('other'),note(),note(nid='two',text='Second'),note(nid='n',text='Overwrite'),note('missing'),note(nid='',text='bad'),note(nid='blank',text=' '),note('other'),stored_notes(),{'op':'restart'},stored_notes()])
 assert rows[2]['status']==rows[3]['status']==rows[8]['status']==201
 fields(rows[2]['body'],{'note_id':'n','text':'Synthetic note','active':True})
 for i,status in [(4,409),(5,404),(6,400),(7,400)]:err(rows[i],status)
 expected=[{'note_id':'n','text':'Synthetic note','active':True},{'note_id':'two','text':'Second','active':True}]
 assert note_rows(rows[9])==note_rows(rows[11])==expected

def test_ru_004_configured_inactive_history():
 rows=observe([create(typ='archive'),note(),create('normal',typ='Archive'),note('normal'),stored_notes(),stored_notes('normal'),{'op':'restart','types':''},stored_notes(),note(nid='later'),stored_notes()],types='archive,void')
 assert rows[1]['status']==201 and rows[1]['body']['active'] is False and rows[3]['body']['active'] is True
 old={'note_id':'n','text':'Synthetic note','active':False}
 for i in [4,7]:assert note_rows(rows[i])==[old]
 assert note_rows(rows[5])==[{'note_id':'n','text':'Synthetic note','active':True}]
 assert note_rows(rows[9])==[old,{'note_id':'later','text':'Synthetic note','active':True}]

def test_ru_005_idempotency_and_atomic_cache_failure():
 trigger="CREATE TRIGGER fail_cache BEFORE INSERT ON responses WHEN NEW.request_id='fail-key' BEGIN SELECT RAISE(ABORT,'synthetic fault'); END"
 rows=observe([create('first',key='once'),create('second',key='once'),get('second'),note('first',key='note-once'),{'op':'restart'},create('third',key='once'),note('first',nid='changed',key='note-once'),get('first'),{'op':'parallel','requests':[create('r'+str(i),key='race-key') for i in range(5)]},{'op':'sql','sql':'SELECT COUNT(*) FROM transactions WHERE id LIKE ?','params':['r%']},req('POST','/unknown',{},'saved-error'),create('error-replay',key='saved-error'),get('error-replay'),{'op':'sql','sql':trigger},create('rollback',key='fail-key'),get('rollback'),{'op':'sql','sql':'SELECT COUNT(*) FROM responses WHERE request_id=?','params':['fail-key']}])
 assert rows[0]['status']==201 and rows[0]==rows[1]==rows[5];err(rows[2],404)
 assert rows[3]['status']==201 and rows[3]==rows[6]
 assert records(rows[7]['body']['notes'])==records(rows[7]['body']['active_notes'])==[{'note_id':'n','text':'Synthetic note','active':True}]
 assert all(x==rows[8][0] for x in rows[8]) and rows[8][0]['status']==201 and rows[9]['rows']==[[1]]
 assert rows[10]==rows[11];err(rows[10],404);err(rows[12],404)
 assert rows[14]['status']>=400;err(rows[15],404);assert rows[16]['rows']==[[0]]

 # GET history/filtering belongs to this gate; seed only the declared storage schema.
 seeded=observe([
  {'op':'sql','sql':'INSERT INTO transactions(id,amount,type) VALUES(?,?,?)','params':['audit',7.25,'archive']},
  {'op':'sql','sql':'INSERT INTO notes(transaction_id,note_id,text,active) VALUES(?,?,?,?)','params':['audit','old','Inactive history',0]},
  {'op':'sql','sql':'INSERT INTO notes(transaction_id,note_id,text,active) VALUES(?,?,?,?)','params':['audit','new','Active note',1]},
  get('audit'),get('absent'),{'op':'restart'},get('audit')])
 history=[{'note_id':'old','text':'Inactive history','active':False},{'note_id':'new','text':'Active note','active':True}]
 for i in [3,6]:
  assert seeded[i]['status']==200
  fields(seeded[i]['body'],{'transaction_id':'audit','amount':7.25,'type':'archive'})
  assert records(seeded[i]['body']['notes'])==history and records(seeded[i]['body']['active_notes'])==history[1:]
  assert all(type(note['active']) is bool for note in seeded[i]['body']['notes'])
 err(seeded[4],404)

 # A POST cache entry must neither hijack GET nor be created by malformed JSON.
 boundary=observe([create('get-target',key='post-key'),
  req('GET','/transactions/get-target',key='post-key'),
  req('GET','/transactions/missing',key='post-key'),
  req('GET','/transactions/get-target',key='get-only-key'),
  create('after-get',key='get-only-key'),
  {'method':'POST','path':'/transactions','raw':'{','headers':{'Idempotency-Key':'parse-key'}},
  {'op':'restart'},create('after-parse',key='parse-key'),get('after-parse')])
 assert boundary[1]['status']==200
 fields(boundary[1]['body'],{'transaction_id':'get-target','amount':12.5,'type':'normal','notes':[],'active_notes':[]})
 err(boundary[2],404);assert boundary[3]['status']==200 and boundary[4]['status']==201
 err(boundary[5],400);assert boundary[7]['status']==201 and boundary[8]['status']==200
 fields(boundary[8]['body'],{'transaction_id':'after-parse','amount':12.5,'type':'normal'})
