"""Protected independent adapter/SQLite/CSV preparation, no candidate code."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pipeline_support import AdapterService,run_as

def main():
    if os.geteuid()!=0:raise RuntimeError('Manager prepares environment before budget')
    adapter=AdapterService(port=8081).start()
    try:
        run_as(1000,'''import csv,io,json,os,pathlib,sqlite3,sys,tempfile
from urllib.parse import quote
from urllib.request import Request,urlopen
assert os.getuid()==1000 and not os.access('/private',os.R_OK) and not os.access(sys.argv[1],os.R_OK)
assert not os.access('/public_tests/adapter_fixture.py',os.W_OK)
assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0
with tempfile.TemporaryDirectory() as folder:
 db=sqlite3.connect(folder+'/probe.sqlite3');db.execute('CREATE TABLE probe(value INTEGER)');db.execute('INSERT INTO probe VALUES(1)');db.rollback();assert not db.execute('SELECT * FROM probe').fetchall()
stream=io.StringIO(newline='');csv.writer(stream).writerow(['comma,quote"',3]);assert list(csv.reader(io.StringIO(stream.getvalue())))[0]==['comma,quote"','3']
key='probe '+chr(0x4e2d)+chr(10);payload={'request_id':key,'target':'table','report':{'synthetic':True}}
request=Request('http://127.0.0.1:8081/deliveries/table',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Idempotency-Key':quote(key,safe='')})
with urlopen(request,timeout=5) as response:assert json.load(response)['request_id']==key
with urlopen('http://127.0.0.1:8081/receipts/table',timeout=5) as response:assert json.load(response)['receipts']==[payload]
''',adapter.state)
        run_as(2000,"import os,pathlib;assert not os.access('/private',os.R_OK);assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0")
        adapter.reset();Path('/private/adapter-service.json').write_text(json.dumps({'pid':adapter.process.pid,'state':str(adapter.state),'url':adapter.url}))
        print(json.dumps({'passed':True,'candidate_code_loaded':False,'candidate_uid':1000,'candidate_capabilities':0,'adapter_uid':2000,'adapter_storage_denied':True,'adapter_private_access_denied':True,'sqlite_transaction':True,'actual_csv_roundtrip':True,'actual_http_receipt':True,'unicode_header_roundtrip':True,'adapter_ready':adapter.url,'dependencies_installed_during_attempt':False}))
    except BaseException:adapter.close();raise

if __name__=='__main__':main()
