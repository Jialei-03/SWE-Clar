"""Prepare independent tools, synthetic identities and starting supplier before budget."""
import subprocess,sys,json
code="""from pathlib import Path
import json,secrets,sqlite3,os,io
from importlib.metadata import version
from PIL import Image
assert version('Pillow')=='12.3.0'
buf=io.BytesIO();Image.new('RGB',(3,3),'blue').save(buf,format='JPEG')
with Image.open(io.BytesIO(buf.getvalue())) as im:im.load();assert im.size==(3,3)
root=Path('/workspace/runtime');root.mkdir(exist_ok=True)
identities=root/'identities.json'
if not identities.exists():
 identities.write_text(json.dumps({secrets.token_hex(20):{'id':'demo-reviewer','role':'review'},secrets.token_hex(20):{'id':'demo-supplier','role':'supplier','supplier_id':'sample-supplier'}},indent=2)+'\\n');os.chmod(identities,0o600)
with sqlite3.connect(root/'records.sqlite') as db:
 db.execute('CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY,name TEXT NOT NULL)')
 db.execute('INSERT OR IGNORE INTO suppliers VALUES (?,?)',('sample-supplier','Synthetic supplier'))
"""
subprocess.run([sys.executable,'-I','-c',code],user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({'passed':True,'pillow':'12.3.0','sqlite_ready':True,'development_identities':'runtime/identities.json','prepared_before_budget':True}))
