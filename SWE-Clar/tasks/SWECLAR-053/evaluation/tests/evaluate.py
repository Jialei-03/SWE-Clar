import json,subprocess,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.dont_write_bytecode=True
import test_levels

def main():
    if not Path(os.environ.get('LEVELS_HOST_HELPER','/public_tests/invoke.py')).is_file():return {'harness_ok':False,'results':[],'error':'Missing invocation helper'}
    rows=[]
    for i in range(1,7):
        try:
            for name in sorted(n for n in dir(test_levels) if n.startswith(f'test_ru_{i:03}_')):getattr(test_levels,name)()
            passed,detail=True,'passed'
        except subprocess.TimeoutExpired:return {'harness_ok':False,'results':[],'error':'Unattributed timeout'}
        except Exception as error:passed,detail=False,type(error).__name__+': '+str(error)
        rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
