"""Prepare writable generated-data storage before the candidate budget."""
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ui_support import identity
code='''import json,os,pathlib
root=pathlib.Path('/workspace/runtime');root.mkdir(exist_ok=True)
probe=root/'write-probe';probe.write_text('ready');probe.unlink()
exclude=pathlib.Path('/workspace/.git/info/exclude')
if exclude.parent.is_dir():
 previous=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in previous.splitlines():exclude.write_text(previous+chr(10)+'/runtime/'+chr(10))
print(json.dumps({'passed':True,'uid':os.getuid()}))
'''
r=json.loads(subprocess.check_output([sys.executable,'-I','-c',code],text=True,**identity()));assert r['passed'] and r['uid']==1000
print(json.dumps(r))
