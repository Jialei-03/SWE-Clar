"""Public filesystem setup and observation; candidate executes in a separate child."""
import base64,hashlib,json,os,resource,signal,subprocess,sys,tempfile
from pathlib import Path
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='migration-files-') as temp:
 root=Path(temp)
 for name in ['source','destination','outside']:(root/name).mkdir()
 for path,item in r.get('files',{}).items():
  p=root/path;assert p.resolve().is_relative_to(root);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(item['base64'])*item.get('repeat',1))
 for link in r.get('symlinks',[]):
  p=root/link['path'];target=root/link['target'];assert p.parent.resolve().is_relative_to(root) and target.resolve().is_relative_to(root);p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target,target_is_directory=link.get('directory',False))
 def snapshot():
  output={}
  for p in root.rglob('*'):
   if p.is_symlink():output[str(p.relative_to(root))]={'symlink':str(p.readlink()).replace(str(root),'<fixture>')}
   elif p.is_file():
    data=p.read_bytes();item={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    if len(data)<=16384:item['base64']=base64.b64encode(data).decode()
    output[str(p.relative_to(root))]=item
  return output
 before=snapshot()
 if 'file_limit' in r:
  signal.signal(signal.SIGXFSZ,signal.SIG_IGN);resource.setrlimit(resource.RLIMIT_FSIZE,(r['file_limit'],r['file_limit']))
 for op in r['operations']:
  request={'project':r['project'],'assets':op['assets'],'taxonomy':op['taxonomy'],'source':str(root/op.get('source','source')),'destination':str(root/op.get('destination','destination'))}
  if op.get('via')=='cli':args=[sys.executable,str(Path(r['project'])/'cli.py'),'--source',request['source'],'--destination',request['destination']]
  else:args=[sys.executable,'-I','/public_tests/invoke.py']
  p=subprocess.run(args,input=json.dumps(request),text=True,capture_output=True,cwd=r['project'],timeout=15)
  value=json.loads(p.stdout) if p.stdout.strip() else None
  if op.get('via')=='cli':value={'report':value}
  rows.append({'returncode':p.returncode,'value':value,'stderr':p.stderr[-1000:],'files':snapshot()})
 print(json.dumps({'before':before,'observations':rows}))
