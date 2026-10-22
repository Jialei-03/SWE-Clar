"""Protected structured requirement runner using only the standard library."""
import json,os,sys
from pathlib import Path
TESTS=Path(__file__).resolve().parent
PUBLIC=Path('/public_tests')
def main():
 if os.geteuid()!=0:return {'harness_ok':False,'error':'Benchmark management identity required','results':[]}
 if any(not p.is_file() for p in [PUBLIC/'invoke.py',TESTS/'candidate_proxy.py',TESTS/'test_solution.py']):return {'harness_ok':False,'error':'Missing evaluator helper','results':[]}
 sys.path.insert(0,str(TESTS))
 import test_solution
 modules=[test_solution]
 rows=[]
 for i in range(1,6):
  prefix=f'test_ru_{i:03}_';checks=[(name,fn) for name,fn in sorted([(name,fn) for module in modules for name,fn in vars(module).items()],key=lambda pair:pair[0]) if name.startswith(prefix) and callable(fn)]
  if not checks:return {'harness_ok':False,'error':'Missing requirement checks','results':rows}
  failures=[]
  for name,fn in checks:
   try:fn()
   except (TimeoutError,__import__("subprocess").TimeoutExpired):return {'harness_ok':False,'error':'Unattributed candidate invocation timeout; reproduce before scoring','results':rows}
   except Exception as e:failures.append({'test':name,'error':type(e).__name__+': '+str(e)})
  rows.append({'ru_id':f'RU-{i:03}','passed':not failures,'failures':failures})
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
