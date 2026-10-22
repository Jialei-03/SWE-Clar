import os,sys
from pathlib import Path
root=Path.cwd();(root/'runtime').mkdir(exist_ok=True)
os.execve(sys.executable,[sys.executable,str(root/'server.py')],{'PATH':os.environ['PATH'],'HOME':'/tmp','PORT':os.environ.get('PORT','8080'),'GRAPH_URL':'http://127.0.0.1:23083/network','STATE_PATH':str(root/'runtime/state.json'),'PYTHONDONTWRITEBYTECODE':'1'})
