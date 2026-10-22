import json,os,subprocess,sys
from pathlib import Path
def call(state,action,fetch_text=None):
    root=Path(os.environ['CANDIDATE_ROOT']);request={'project':str(root),'state':state,'action':action}
    if fetch_text is not None:
        try:request['csv']=fetch_text(action['url'])
        except OSError:request['fetch_error']=True
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout);assert 'error' not in result,result
    assert result['after']==[state,action],'Inputs mutated'
    assert isinstance(result['result'],dict)
    if fetch_text is not None:assert result['fetch_calls']==[action['url']],'Injected source must actually be consumed once'
    return result['result']
