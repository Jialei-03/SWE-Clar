import json,sys
from storage import LedgerStore
store=LedgerStore(sys.argv[1]);mode=sys.argv[2]
if mode=='init':result=store.init(json.load(sys.stdin))
elif mode=='apply':result=store.apply(json.load(sys.stdin))
elif mode=='snapshot':result=store.snapshot()
else:raise ValueError('unknown_command')
json.dump(result,sys.stdout,allow_nan=False);print()
