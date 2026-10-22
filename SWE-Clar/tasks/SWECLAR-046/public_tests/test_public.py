import json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,os.getcwd())
from local_service import LocalService
from pipeline_client import PipelineClient

with tempfile.TemporaryDirectory() as data:
    db=Path(data)/'provider.db';rows=json.loads(Path('source.json').read_text())
    with LocalService(db,rows) as provider:
        client=PipelineClient({'source':provider.url+'/source'},{'destination':provider.url+'/destination'},provider.url+'/outreach',provider.token)
        assert client.read_source('source')==rows and client.read_destination('destination')=={}
        def send(method,path,body,key=None):
            headers={'Authorization':'Bearer '+provider.token,'Content-Type':'application/json'}
            if key:headers['Idempotency-Key']=key
            with urlopen(Request(provider.url+path,data=json.dumps(body).encode(),headers=headers,method=method),timeout=3) as r:return json.load(r)
        row={'source_id':'demo','name':'Synthetic'}
        assert send('PUT','/destination/demo',row)['source_id']=='demo'
        delivery={'delivery_id':'sample-delivery','email':'sample@example.test'}
        for _ in range(2):assert send('POST','/outreach',delivery,'sample-delivery')['accepted']
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT count(*) FROM deliveries').fetchone()==(1,)
    with LocalService(db,rows) as provider:
        client=PipelineClient({}, {'destination':provider.url+'/destination'},provider.url+'/outreach',provider.token)
        assert client.read_destination('destination')=={'demo':row}
    p=subprocess.run([sys.executable,'cli.py','--database',str(Path(data)/'console.db')],input=Path('example.json').read_text(),capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    assert isinstance(json.loads(p.stdout),dict)
print('Prepared HTTP source, destination, local queue, persistence and console checks passed.')
