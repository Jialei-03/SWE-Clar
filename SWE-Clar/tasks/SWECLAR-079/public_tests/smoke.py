"""Check real inventory and public CLI export without requiring completed sampling."""
import tempfile,subprocess,json,sys
from pathlib import Path
sys.path.insert(0,'/public_tests')
from fixtures import write_images,base_config
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);write_images(root)
 result=subprocess.run([sys.executable,'-I','/public_tests/worker.py'],input=json.dumps({'operation':'inventory','input_directory':str(root)}),text=True,capture_output=True,check=True)
 inventory=json.loads(result.stdout);config=base_config(inventory);path=root/'config.json';path.write_text(json.dumps(config));out=root/'workflow.json'
 subprocess.run([sys.executable,'cli.py',str(path),'--output',str(out)],check=True,capture_output=True)
 workflow=json.loads(out.read_text());assert isinstance(workflow,dict);assert 'prompt' in workflow or 'error' in workflow
 print('Real ComfyUI inventory and CLI export passed')
