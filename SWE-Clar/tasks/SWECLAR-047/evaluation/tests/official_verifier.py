import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    test_dir=Path(__file__).resolve().parent
    log=Path(os.environ.get('SWECLAR_LOG_DIR','/tmp/verifier'))
    log.mkdir(parents=True,exist_ok=True)
    expected=json.loads((test_dir/'expected_gates.json').read_text())['expected_gate_ids']
    gates=[]
    error=None
    try:
        completed=subprocess.run([sys.executable,'-I',str(test_dir/'notebook_contract.py')],
                                 text=True,capture_output=True,timeout=180)
        (log/'evaluator.log').write_text(completed.stdout+'\n'+completed.stderr)
        if completed.returncode not in (0,2):
            raise ValueError('Evaluator crashed: '+completed.stderr[-3000:])
        payload=json.loads(completed.stdout)
        if completed.returncode!=0 or payload.get('harness_ok') is not True:
            raise ValueError('Evaluator reported infrastructure failure: '+completed.stderr[-1500:]+' '+str(payload.get('infrastructure_errors',[])))
        results=payload['results']
        if [r['ru_id']+'-T01' for r in results]!=expected or any(type(r['passed']) is not bool for r in results):
            raise ValueError('Incomplete, duplicated or malformed gate results')
        gates=[{'id':r['ru_id']+'-T01','verdict':r['passed'],'skipped':False,'detail':r.get('detail','passed')} for r in results]
    except (ValueError,KeyError,TypeError,OSError,subprocess.TimeoutExpired) as exception:
        error=type(exception).__name__+': '+str(exception)
        gates=[{'id':gate,'verdict':False,'skipped':True,'detail':'Invalid run: '+error} for gate in expected]
    report={'gates':gates,'reward':int(all(g['verdict'] for g in gates)) if error is None else None,
            'harness_ok':error is None,'infrastructure_error':error}
    (log/'gates.json').write_text(json.dumps(report,indent=2)+'\n')
    if error is None:
        (log/'reward.txt').write_text(str(report['reward'])+'\n')
    else:
        (log/'reward.txt').unlink(missing_ok=True)
    print(json.dumps(report))
    return 0 if error is None else 2


if __name__=='__main__':
    raise SystemExit(main())
