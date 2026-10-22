"""Prepare the synthetic development workspace before candidate time starts."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from inspection_support import identity
code='''import json,os,pathlib
root=pathlib.Path('/workspace/runtime');root.mkdir(exist_ok=True)
config=root/'config.json'
if not config.exists():
 config.write_bytes(pathlib.Path('/public_tests/development.json').read_bytes());config.chmod(0o600)
probe=root/'write-probe';probe.write_text('ready');probe.unlink()
exclude=pathlib.Path('/workspace/.git/info/exclude')
if exclude.parent.is_dir():
 previous=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in previous.splitlines():exclude.write_text(previous+chr(10)+'/runtime/'+chr(10))
print(json.dumps({'passed':True,'uid':os.getuid(),'config':str(config)}))
'''
r=json.loads(subprocess.check_output([sys.executable,'-I','-c',code],text=True,**identity()))
assert r['passed'] and r['uid']==1000
print(json.dumps(r))
