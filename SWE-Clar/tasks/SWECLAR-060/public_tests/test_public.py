from pathlib import Path
import sys,os,json,subprocess
root=os.environ.get('CANDIDATE_ROOT','/workspace');request={'project':root,'operations':[{'op':'inspect'},{'op':'move','key':'ArrowRight'},{'op':'http','path':'/health'}]}
p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('browser_worker.py'))],input=json.dumps(request),capture_output=True,text=True,timeout=35);assert p.returncode==0,p.stderr
rows=json.loads(p.stdout)['observations'];assert all(not x.get('operation_error') and not x.get('page_errors') for x in rows);assert rows[0]['canvas']!=rows[1]['canvas'];assert rows[-1]['response'].get('ok') is True
print('PASS: HTTP startup, canvas rendering and keyboard movement')
