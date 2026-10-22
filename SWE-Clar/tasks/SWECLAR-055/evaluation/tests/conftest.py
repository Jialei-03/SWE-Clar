import json,os,subprocess,sys
from pathlib import Path
from types import SimpleNamespace

def invoke(function,*args,**kwargs):
    root=Path(os.environ['CANDIDATE_ROOT'])
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(root),'function':function,'args':args,'kwargs':kwargs}),capture_output=True,text=True,timeout=12,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout);assert 'error' not in result,result
    assert json.dumps(result['after'],sort_keys=True)==json.dumps(list(args),sort_keys=True),'Inputs mutated'
    assert isinstance(result['result'],dict)
    return result['result']
def load_solution():
    return SimpleNamespace(process_iot_action=lambda *a,**kw:invoke('process_iot_action',*a,**kw),ingest_mqtt=lambda *a,**kw:invoke('ingest_mqtt',*a,**kw))
