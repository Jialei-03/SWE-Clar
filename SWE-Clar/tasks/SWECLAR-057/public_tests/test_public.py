from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from service_support import run_session
r=run_session([{'op':'mount'},{'op':'enter_text','key':'username','text':'demo'},{'op':'enter_text','key':'password','text':'synthetic'},{'op':'tap','key':'login'}],initial={})
assert all(not x.get('operation_error') and not x.get('render_errors') for x in r['observations'])
assert 'General consultation' in r['observations'][-1]['texts']
print('PASS: actual Flutter login and service rendering')
