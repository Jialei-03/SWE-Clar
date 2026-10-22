"""Prepare synthetic development configuration before the candidate budget."""
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from stream_support import identity

code='''import json,os,pathlib
root=pathlib.Path('/workspace/runtime');root.mkdir(exist_ok=True)
config=root/'config.json'
if not config.exists():
 config.write_text(json.dumps({'admin_token':'demo-admin','stream_keys':{'alpha':'demo-alpha','beta':'demo-beta','gamma':'demo-gamma'},'media_root':str(root/'media')}))
 config.chmod(0o600)
probe=root/'write-probe';probe.write_text('ready');probe.unlink()
exclude=pathlib.Path('/workspace/.git/info/exclude')
if exclude.parent.is_dir():
 previous=exclude.read_text() if exclude.exists() else ''
 if '/runtime/' not in previous.splitlines():exclude.write_text(previous+'\\n/runtime/\\n')
print(json.dumps({'prepared':True,'uid':os.getuid(),'config':str(config)}))
'''
result=json.loads(subprocess.check_output([sys.executable,'-I','-c',code],**identity(),text=True))
assert result['prepared'] and result['uid']==1000
print(json.dumps({'passed':True,'workspace_prepared':True,'candidate_uid':1000}))
