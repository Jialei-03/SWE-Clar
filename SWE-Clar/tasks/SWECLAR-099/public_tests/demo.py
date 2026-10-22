import os,sys,json,tempfile,subprocess
from pathlib import Path
from photo_fixtures import configuration
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'config.json').write_text(json.dumps(configuration()))
 subprocess.run([sys.executable,'server.py'],env={**os.environ,'PHOTO_CONFIG':str(p/'config.json'),'PHOTO_DATABASE':str(p/'state.db'),'PHOTO_ASSETS':str(p/'images'),'PORT':'0'},check=True)
