import json,os,subprocess,sys
from pathlib import Path
class ServiceConfig:
    def __init__(self,**config):self.config=config
def call(state,event,service=None):
    root=Path(os.environ['CANDIDATE_ROOT']);request={'project':str(root),'state':state,'event':event,'config':service.config if service else None}
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout);assert 'error' not in result,result
    assert json.dumps(result['after'],sort_keys=True)==json.dumps([state,event],sort_keys=True),'Inputs mutated'
    assert isinstance(result['result'],dict)
    return result['result']
