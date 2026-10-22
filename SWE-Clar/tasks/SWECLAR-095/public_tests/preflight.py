from pathlib import Path
import os,json,shutil,subprocess
import playwright.sync_api
assert shutil.which('node') and Path(os.environ['UI_NODE_MODULES'],'react').is_dir()
assert all(Path('/public_tests',n).is_file() for n in ['service_launcher.py','browser_launcher.py','browser_isolation.py'])
print(json.dumps({'passed':True,'node':subprocess.check_output(['node','--version'],text=True).strip(),'react':True,'browser':True}))
