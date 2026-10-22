"""Prepared tools and supplied file/stdin console smoke test."""
import json,subprocess,sys
from pathlib import Path
for args,data in [(['example.json'],None),([],Path('example.json').read_text())]:
    p=subprocess.run([sys.executable,'cli.py',*args],input=data,capture_output=True,text=True,check=True)
    result=json.loads(p.stdout)
    assert all(isinstance(result[k],list) for k in ['active_levels','display_levels','break_events'])
print('Python and supplied JSON file/stdin console smoke passed; level business logic is unfinished in starter.')
