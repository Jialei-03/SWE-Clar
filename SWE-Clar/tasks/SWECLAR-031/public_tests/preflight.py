"""Generate synthetic practice media before the coding budget as the workspace user."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'));public=Path(__file__).resolve().parent
identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
subprocess.run([sys.executable,'-I',str(public/'make_fixtures.py'),str(root/'runtime')],check=True,timeout=30,**identity)
probe="import json,pathlib,subprocess;root=pathlib.Path('runtime');data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(root/'demo.webm')]));assert {'audio','video'}<={s['codec_type'] for s in data['streams']};assert (root/'demo.mid').read_bytes().startswith(b'MThd');print(json.dumps({'passed':True,'media':'synthetic WebM','midi':'synthetic MIDI'}))"
subprocess.run([sys.executable,'-I','-c',probe],cwd=root,check=True,**identity)

exclude="from pathlib import Path;p=Path('.git/info/exclude');p.parent.mkdir(parents=True,exist_ok=True);s=p.read_text() if p.exists() else '';p.write_text(s+('\\n/runtime/\\n' if '/runtime/' not in s.splitlines() else ''))"
subprocess.run([sys.executable,'-I','-c',exclude],cwd=root,check=True,**identity)
