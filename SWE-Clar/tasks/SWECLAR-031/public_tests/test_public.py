"""Check disclosed source parsing and actual recording playback in the prepared workspace."""
import os,select,subprocess,sys
from pathlib import Path
root=Path(os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()));public=Path(__file__).resolve().parent
assert (root/'runtime/config.json').is_file(),'Benchmark preflight must supply runtime assets before execution'
env={**os.environ,'HOME':str(root/'runtime'),'PORT':'0'}
subprocess.run(['node','build.mjs','runtime/dist'],cwd=root,env=env,check=True,timeout=30)
server=subprocess.Popen([sys.executable,'serve.py','runtime/dist'],cwd=root,env=env,stdout=subprocess.PIPE,text=True)
try:
    assert select.select([server.stdout],[],[],5)[0],'Server did not announce port'
    port=server.stdout.readline().strip();assert port.isdigit()
    subprocess.run(['node',str(public/'public_probe.cjs'),'http://127.0.0.1:'+port],cwd=root,env=env,check=True,timeout=30)
finally:server.terminate();server.wait(timeout=5)
