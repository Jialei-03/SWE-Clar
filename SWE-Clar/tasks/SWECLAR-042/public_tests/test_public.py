"""Exercise existing console and SQLite persistence, not hidden business policy."""
import json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/workspace')
request=json.loads((root/'example.json').read_text())
with tempfile.TemporaryDirectory() as directory:
    database=Path(directory)/'workflow.db'
    process=subprocess.run([sys.executable,str(root/'cli.py'),str(database)],input=json.dumps(request),capture_output=True,text=True,check=True,cwd=root,timeout=15)
    result=json.loads(process.stdout);assert isinstance(result,dict) and 'error' not in result
    with sqlite3.connect(database) as connection:
        saved=json.loads(connection.execute('SELECT state FROM workflow WHERE singleton=1').fetchone()[0])
    assert saved==result and saved['users']==request['seed']['users']
print(json.dumps({'passed':True,'console_json':True,'sqlite_commit':True,'business_correctness':'not established by smoke checks'}))
