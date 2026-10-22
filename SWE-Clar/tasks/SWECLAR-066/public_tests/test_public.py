import json,subprocess,sys
from pathlib import Path
r=subprocess.run([sys.executable,'-I','/public_tests/browser_worker.py'],input=json.dumps({'project':str(Path.cwd()),'operations':[{'op':'inspect'}]}),capture_output=True,text=True,check=True);row=json.loads(r.stdout)['observations'][0];assert not row.get('operation_error') and not row.get('page_errors'),row.get('operation_error');assert row['webgl']['present'] and row['webgl']['depth'];print('Public WebGL browser startup passed')
