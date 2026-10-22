"""Start the candidate portal against its already-provisioned local database."""
import json,os,sys
from pathlib import Path
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
if os.geteuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
config=json.loads((root/'runtime/connection.json').read_text())
env={k:os.environ[k] for k in ['PATH','NODE_PATH','HOME'] if k in os.environ}
env.update(config);env['PORT']=os.environ.get('PORT','8080')
os.chdir(root);os.execvpe('node',['node','server.cjs'],env)
