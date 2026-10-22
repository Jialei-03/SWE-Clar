"""Protected assertions invoke only unprivileged candidate processes."""
from pathlib import Path
import json,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_solution
import adapters
def main():
    if any(not Path('/public_tests/'+name).is_file() for name in ['invoke.py','browser_observe.py']):return {'harness_ok':False,'results':[],'error':'Missing invocation/browser helper'}
    rows=[]
    for i in range(1,6):
        try:
            getattr(test_solution,f'test_ru_{i:03}')()
            if i==1:adapters.run()
            passed,detail=True,'passed'
        except (subprocess.TimeoutExpired,adapters.InfrastructureError):return {'harness_ok':False,'results':[],'error':'Browser infrastructure failure or unattributed timeout; reproduce before scoring'}
        except Exception as error:passed,detail=False,type(error).__name__+': '+str(error)
        rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
    return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
