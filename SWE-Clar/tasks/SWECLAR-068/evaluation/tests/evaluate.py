import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_solution

def main():
    if not all(Path(p).is_file() for p in ['/public_tests/browser_launcher.py','/public_tests/invoke.py']):return {'harness_ok':False,'results':[],'error':'Missing invocation helper'}
    rows=[]
    for i in range(1,6):
        try:
            for name in sorted(n for n in dir(test_solution) if n.startswith(f'test_ru_{i:03}_')):getattr(test_solution,name)()

            passed,detail=True,'passed'
        except subprocess.TimeoutExpired:return {'harness_ok':False,'results':[],'error':'Unattributed timeout'}
        except Exception as error:passed,detail=False,type(error).__name__+': '+str(error)
        rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
