"""Benchmark-managed writable workspace preparation, before the coding budget."""
import json,os,sqlite3,tempfile,subprocess,sys
from pathlib import Path
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
runtime=root/'runtime'
subprocess.run([sys.executable,'-I','-c','from pathlib import Path;import sys;Path(sys.argv[1]).mkdir(exist_ok=True)',str(runtime)],check=True,**({'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}))
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'health.db'
    with sqlite3.connect(p) as db:
        db.execute('create table health(value integer)');db.execute('insert into health values(42)')
    with sqlite3.connect(p) as db:assert db.execute('select value from health').fetchone()==(42,)
print(json.dumps({'passed':True,'runtime':'runtime','sqlite':sqlite3.sqlite_version}))
