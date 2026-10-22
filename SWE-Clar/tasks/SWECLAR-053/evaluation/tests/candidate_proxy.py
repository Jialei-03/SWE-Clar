import json,os,subprocess,sys
from pathlib import Path

def call(bars, lookback, **options):
    root=Path(os.environ['CANDIDATE_ROOT'])
    helper=os.environ.get('LEVELS_HOST_HELPER','/public_tests/invoke.py')
    kwargs={} if os.environ.get('LEVELS_HOST_HELPER') else {'user':1000,'group':1000,'extra_groups':[]}
    p=subprocess.run([sys.executable,'-I',helper],input=json.dumps({'project':str(root),'bars':bars,'lookback':lookback,'options':options}),capture_output=True,text=True,timeout=8,cwd=root,env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},**kwargs)
    assert p.returncode==0,p.stderr[-800:]
    result=json.loads(p.stdout)
    # JSON NaN is used solely to test rejection; NaN does not equal itself.
    assert json.dumps(result['after'],sort_keys=True)==json.dumps(bars,sort_keys=True),'Inputs mutated'
    return result

def run(bars,lookback,**options):
    result=call(bars,lookback,**options);assert 'error' not in result,result
    value=result['result'];assert isinstance(value,dict)
    return value
