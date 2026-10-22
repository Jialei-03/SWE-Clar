import json,sqlite3,tempfile,urllib.request
from pathlib import Path
import sys,os
sys.path.insert(0,os.getcwd())
from sync_service import SyncService

def request(url,value=None):
    body=None if value is None else json.dumps(value).encode()
    with urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'}),timeout=3) as response:return json.load(response)

with tempfile.TemporaryDirectory() as data:
    database=Path(data)/'sync.db'
    event={'event_id':'event-one','kind':'topup','terminal_imei':'terminal-synthetic','amount':12.5}
    with SyncService(database) as service:
        for _ in range(2):assert request(service.url+'/sync',{'events':[event]})['accepted_ids']==['event-one']
        result=request(service.url+'/sync',{'events':[{**event,'amount':99},{**event,'event_id':'event-two'}]})
        assert result=={'accepted_ids':['event-two'],'conflicting_ids':['event-one']}
        assert len(request(service.url+'/events')['events'])==2
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()==(2,)
        assert json.loads(db.execute('SELECT body FROM events WHERE id=?',('event-one',)).fetchone()[0])==event
    with SyncService(database) as service:
        assert len(request(service.url+'/events')['events'])==2
        assert request(service.url+'/sync',{'events':[event]})['accepted_ids']==['event-one']
print('HTTP/SQLite acknowledgement, duplicate replay, conflicting payload and restart checks passed.')
import subprocess
with tempfile.TemporaryDirectory() as data:
    result=subprocess.run([sys.executable,'cli.py','--server-db',str(Path(data)/'console.db')],input=Path('example.json').read_text(),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert isinstance(json.loads(result.stdout),dict)
print('Supplied console starts with synthetic input.')
