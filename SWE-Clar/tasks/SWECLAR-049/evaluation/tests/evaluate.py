import json,os,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_solution

def main():
 if not Path('/public_tests/invoke.py').is_file():return {'harness_ok':False,'results':[],'infrastructure_errors':['Missing invocation helper']}
 rows=[]
 for i in range(1,6):
  try:
   with tempfile.TemporaryDirectory(prefix='intake-case-') as d:
    os.chmod(d,0o777)
    for name in sorted(n for n in dir(test_solution) if n.startswith(f'test_ru_{i:03}_')):getattr(test_solution,name)(Path(d))
   passed,detail=True,'passed'
  except (subprocess.TimeoutExpired,test_solution.InfrastructureError):return {'harness_ok':False,'results':[],'infrastructure_errors':['Unattributed timeout']}
  except Exception as e:passed,detail=False,type(e).__name__+': '+str(e)
  rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
