"""Protected parent collects five independent RU results; candidate imports stay in worker."""
from pathlib import Path
import json,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_solution
import boundaries

def main():
    if not Path('/public_tests/invoke.py').is_file():return {'harness_ok':False,'results':[],'error':'Missing candidate invocation helper'}
    rows=[]
    for i in range(1,6):
        try:
            getattr(test_solution,f'test_ru_{i:03}')()
            getattr(boundaries,f'ru{i:03}')()
            passed,detail=True,'passed'
        except subprocess.TimeoutExpired:return {'harness_ok':False,'results':[],'error':'Unattributed timeout; reproduce before scoring'}
        except Exception as error:passed,detail=False,__import__('traceback').format_exc()
        rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
