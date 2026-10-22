"""Neutral adapter for checking the public Store.action interface."""
import contextlib,importlib.util,json,sys
from pathlib import Path
request=json.load(sys.stdin);wire=sys.stdout;sys.path.insert(0,request['project']);sys.dont_write_bytecode=True
try:
    with contextlib.redirect_stdout(sys.stderr):
        from store import Store
        store=Store(request['database'],json.loads(Path(request['identities']).read_text()))
        result=store.action(request['token'],request['action'])
    wire.write(json.dumps({'result':result,'after':request['action']})+'\n')
except Exception as error:wire.write(json.dumps({'error':type(error).__name__+': '+str(error),'after':request['action']})+'\n')
