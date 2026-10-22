import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_solution

def main():
 if not all((Path('/public_tests')/n).is_file() for n in ['browser_worker.py']):return {'harness_ok':False,'results':[],'infrastructure_errors':['Missing public invocation worker']}
 rows=[]
 for i in range(1,6):
  try:
   for name in sorted(n for n in dir(test_solution) if n.startswith(f'test_ru_{i:03}_')):getattr(test_solution,name)()
   passed,detail=True,'passed'
  except subprocess.TimeoutExpired:return {'harness_ok':False,'results':[],'infrastructure_errors':['Unattributed timeout']}
  except Exception as e:passed,detail=False,type(e).__name__+': '+str(e)
  rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
