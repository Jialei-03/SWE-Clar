"""Neutral public adapter for the documented Store.quote interface."""
import os,sys,json
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
for key in list(os.environ):
 if key not in ['PATH','HOME']:del os.environ[key]
project,config,database,sid,action=sys.argv[1:];sys.path.insert(0,project)
from store import Store
from provider import SolarClient
cfg=json.load(open(config));a=json.loads(action);result=Store(database,SolarClient(cfg),cfg['pricing']).quote(sid,a)
print(json.dumps({'action':a,'result':result}))
