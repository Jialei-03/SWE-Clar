import sys,json
from storage import CommandStore
store=CommandStore(sys.argv[1]);mode=sys.argv[2]
if mode=='init':out=store.init(json.load(sys.stdin))
elif mode=='apply':out=store.apply(json.load(sys.stdin))
elif mode=='snapshot':out=store.snapshot()
else:raise ValueError('unknown_command')
json.dump(out,sys.stdout,allow_nan=False);print()
