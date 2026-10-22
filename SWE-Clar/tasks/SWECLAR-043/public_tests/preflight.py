import subprocess,sys,json
subprocess.run([sys.executable,'-I','-c',"from pathlib import Path;import sqlite3;Path('/workspace/runtime').mkdir(exist_ok=True);assert sqlite3.connect(':memory:').execute('SELECT 1').fetchone()==(1,)"],user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({'passed':True,'sqlite_ready':True,'prepared_before_budget':True}))
