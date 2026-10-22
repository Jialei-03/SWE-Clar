import json,os,subprocess,sys
from pathlib import Path
def call(state,action,upload_events=None):
    root=Path(os.environ['CANDIDATE_ROOT']);request={'project':str(root),'state':state,'action':action}
    pending=state.get('pending',{}).get(action.get('terminal_imei'),[])
    if upload_events is not None:
        try:request['reply']=upload_events(pending)
        except OSError:request['upload_error']=True
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout);assert 'error' not in result,result
    assert result['after']==json.dumps([state,action],sort_keys=True),'Inputs mutated'
    assert isinstance(result['result'],dict)
    if upload_events is not None and pending:assert result['upload_calls']==[pending],'Actual pending batch must be uploaded once'
    return result['result']
