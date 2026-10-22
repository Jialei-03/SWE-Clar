"""Public local inventory/callback adapters; no hidden expectations."""
import os,sys,json,builtins
from pathlib import Path
if '--worker' not in sys.argv:
 project=sys.argv[1]
 if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
 os.execve(sys.executable,[sys.executable,'-I',__file__,'--worker',project],{'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
data=json.loads(sys.stdin.read());root=Path(data['workspace']);calls=[];events=[]
class Client:
 def lookup(self,sku):
  calls.append(sku)
  if sku in data.get('failures',[]):raise LookupError('synthetic lookup failure')
  return data.get('values',{}).get(str(sku),{'soh':len(str(sku))+10,'ots':len(str(sku))+4})
def callback(path,action):
 from openpyxl import load_workbook
 path=Path(path);wb=load_workbook(path);values=list(wb['Inventory'].values);wb.close()
 events.append({'workbook':path.relative_to(root).as_posix(),'action':action,'observed_rows':values})
 policy=data['callbacks'].get(action,{})
 if policy.get('fail'):raise RuntimeError('synthetic callback failure')
 if policy.get('write_file'):
  content=policy.get('text',action)
  if policy.get('stock_csv'):content=path.parent.name+','+str(values[1][3])
  (path.parent/policy['write_file']).write_text(content)
def no_input(*args):raise AssertionError('interactive input is forbidden')
builtins.input=no_input
sys.path.insert(0,sys.argv[2]);from inventory_sync import run_inventory_sync
report=run_inventory_sync(root,Client(),callback if data.get('callbacks') is not None else None)
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
print(json.dumps({'report':report,'calls':calls,'callbacks':events,'proof':{'pid':os.getpid(),'uid':os.getuid(),'cap_eff':int(status['CapEff'],16),'environment_keys':sorted(os.environ)}}))
