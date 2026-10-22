import json,os,subprocess,sys
from pathlib import Path
class ServiceConfig:
    def __init__(self,source_urls,destination_urls,outreach_url,token=None):
        self.source_urls=source_urls;self.destination_urls=destination_urls;self.outreach_url=outreach_url;self.token=token
def call(state,action,service):
    root=Path(os.environ['CANDIDATE_ROOT']);request={'project':str(root),'state':state,'action':action,'service':vars(service)}
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout);assert 'error' not in result,result
    assert result['after']==[state,action],'Inputs mutated'
    assert isinstance(result['result'],dict)
    return result['result']
