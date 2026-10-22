"""Protected parent invokes candidates exclusively under ordinary UID1000."""
import json,os,signal,subprocess,sys
from pathlib import Path
def call(players,limit,mode):
    root=Path(os.environ['SWECLAR_PROJECT_DIR'])
    p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(root),'players':players,'limit':limit,'mode':mode}),capture_output=True,text=True,cwd=root,timeout=45,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    assert p.returncode!=-signal.SIGPROF,'Optimization exceeded 15 CPU seconds'
    assert p.returncode==0,'Candidate invocation failed: '+p.stderr[-500:]
    value=json.loads(p.stdout); assert 'error' not in value,value.get('error')
    assert value['after_json']==json.dumps(players,sort_keys=True),'Caller inputs mutated'
    assert isinstance(value['result'],dict)
    return value['result']
