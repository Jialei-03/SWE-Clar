"""Public CLI input/output observation."""
import json,subprocess,sys
from pathlib import Path
r=json.load(sys.stdin);p=subprocess.run([sys.executable,str(Path(r['project'])/'cli.py'),'--offset',str(r.get('offset',0)),'--limit',str(r.get('limit',20))],input=json.dumps(r['request']),capture_output=True,text=True,cwd=r['project'],timeout=10)
print(json.dumps({'returncode':p.returncode,'output':json.loads(p.stdout) if p.stdout.strip() else None,'stderr':p.stderr[-800:]}))
