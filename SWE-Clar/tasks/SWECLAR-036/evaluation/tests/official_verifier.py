#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
GATES = [{'test_id':'RU-001-T01','file':'tests/setup_contract.py','ru_id':'RU-001'}, {'test_id':'RU-002-T01','file':'tests/setup_contract.py','ru_id':'RU-002'}, {'test_id':'RU-003-T01','file':'tests/setup_contract.py','ru_id':'RU-003'}, {'test_id':'RU-004-T01','file':'tests/setup_contract.py','ru_id':'RU-004'}, {'test_id':'RU-005-T01','file':'tests/setup_contract.py','ru_id':'RU-005'}]

def main():
    env=dict(os.environ);env.setdefault('SWECLAR_PROJECT_DIR',str(Path.cwd()))
    try:
        run=subprocess.run([sys.executable,str(Path(__file__).with_name('setup_contract.py'))],env=env,text=True,capture_output=True,timeout=115)
        payload=json.loads(run.stdout.strip().split('\n')[-1])
        rows=payload.get('results',[])
        observed={r['ru_id']:r for r in rows}
        ok=(payload.get('harness_ok') is True and run.returncode in (0,1)
            and len(rows)==len(observed) and set(observed)=={g['ru_id'] for g in GATES}
            and all(type(r.get('passed')) is bool for r in rows))
        detail=payload.get('error') or run.stderr[-2000:] or ('' if ok else 'Invalid structured evaluator results')
    except Exception as error:
        ok=False;observed={};detail='evaluator execution failed: '+str(error)
    gates=[{'id':g['test_id'],'verdict':bool(ok and observed.get(g['ru_id'],{}).get('passed')),'skipped':not ok,'detail':observed.get(g['ru_id'],{}).get('detail') or detail or ('passed' if observed.get(g['ru_id'],{}).get('passed') else 'failed')} for g in GATES]
    log=Path(os.environ.get('SWECLAR_LOG_DIR','/logs/verifier'));log.mkdir(parents=True,exist_ok=True)
    result={'gates':gates,'harness_ok':ok,'reward':int(all(g['verdict'] for g in gates)) if ok else None};(log/'gates.json').write_text(json.dumps(result,indent=2)+'\n')
    if ok:(log/'reward.txt').write_text(str(int(all(g['verdict'] for g in gates)))+'\n')
    else:(log/'reward.txt').unlink(missing_ok=True)
    print(json.dumps(result));return 0 if ok else 2

if __name__=='__main__':raise SystemExit(main())
