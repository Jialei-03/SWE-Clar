"""Prepare pinned native AMD64 environments before any candidate budget starts."""
import argparse,hashlib,importlib.util,json,shutil,subprocess,tempfile
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parent
PROFILES=['python-web','python-web-mqtt','native-control','python-practice','python-vision','python-report']
def output(argv):return subprocess.check_output(argv,text=True).strip()
def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--profile',action='append',help='Defaults to all supported AMD64 profiles; dependencies are included')
 parser.add_argument('--records',type=Path,required=True,help='Output directory outside the dataset')
 parser.add_argument('--cache',type=Path,required=True,help='Verified download cache outside the dataset')
 parser.add_argument('--environments',type=Path,default=ROOT,help='Read-only released environments directory')
 parser.add_argument('--plan',action='store_true')
 args=parser.parse_args()
 root=args.environments.resolve()
 from frozen_extensions import replay,profile_order,pinned_base,verify_child
 names=args.profile or sorted(p.name for p in (root/'amd64').iterdir() if p.is_dir())
 order=profile_order(root,names)
 if args.plan:
  print(json.dumps({'profiles':order}));return
 for p in [args.records,args.cache]:
  if p.resolve().is_relative_to(root.parent):raise SystemExit('Records and cache must be outside the dataset')
  p.mkdir(parents=True,exist_ok=True)
 records={}
 def prepare(name):
  if name in records:return records[name]
  recipe=root/'amd64'/name;lock=json.loads((recipe/'lock.json').read_text());fingerprint=hashes(recipe);record_path=args.records/(name+'.json')
  parent_name=lock.get('base',{}).get('profile',lock.get('base_profile'))
  parent_image=prepare(parent_name)['image'] if parent_name else None
  if record_path.exists():
   record=json.loads(record_path.read_text())
   if parent_image and record.get('base_image')!=parent_image:raise SystemExit('Cached parent changed; use a new records directory')
   if record['recipe_hashes']!=fingerprint:raise SystemExit('Recipe changed; use a new records directory')
   image=json.loads(output(['docker','image','inspect',record['image']]))[0]
   if image['Id']!=record['image'] or image['Architecture']!='amd64':raise SystemExit('Cached image identity mismatch')
   if record['preflight'].get('passed') is not True:raise SystemExit('Cached preflight failed')
   records[name]=record;return record
  if 'base_profile' in lock:
   parent_name=lock['base_profile']
   if parent_name:base=prepare(parent_name)['image']
   else:
    base=lock['compiler_image'];subprocess.run(['docker','pull','--platform','linux/amd64',base],check=True)
   record=replay(root,name,lock,args.cache,base,hashes)
   record_path.write_text(json.dumps(record,indent=2)+'\n');records[name]=record;return record
  parent=lock['base']
  if 'profile' in parent:base=prepare(parent['profile'])['image']
  else:
   base=parent['image'];subprocess.run(['docker','pull','--platform','linux/amd64',base],check=True)
   image=json.loads(output(['docker','image','inspect',base]))[0]
   if image['Architecture']!='amd64':raise SystemExit('Base architecture mismatch')
  with tempfile.TemporaryDirectory(prefix='sweclar-amd64-') as temp:
   ctx=Path(temp);shutil.copytree(recipe,ctx,dirs_exist_ok=True)
   for kind,rows in [('wheels',lock['wheels']),('deb_packages',lock['deb_packages'])]:
    folder=ctx/('wheelhouse' if name in ['python-web','python-web-mqtt'] else 'packages');folder.mkdir(exist_ok=True)
    for row in rows:
     cached=args.cache/row['sha256']
     if not cached.exists():
      with urlopen(row['url'],timeout=120) as f:data=f.read()
      if hashlib.sha256(data).hexdigest()!=row['sha256']:raise SystemExit('Dependency checksum mismatch')
      cached.write_bytes(data)
     if hashlib.sha256(cached.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Cached dependency checksum mismatch')
     shutil.copyfile(cached,folder/row['filename'])
   if lock.get('npm_lock'):
    spec=importlib.util.spec_from_file_location('sweclar_locked_npm',ctx/'dependencies.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.install(ctx/lock['npm_lock'],ctx/'ui')
   with pinned_base(base,output) as (alias,base_info):
    dockerfile=ctx/'Dockerfile';text=dockerfile.read_text()
    text='\n'.join(('FROM '+alias+line[len('FROM '+base):]) if line.startswith('FROM '+base) else line for line in text.splitlines())+'\n'
    dockerfile.write_text(text)
    argv=['docker','build','--platform','linux/amd64','--network','none','--pull=false','--iidfile',str(ctx/'image.id')]
    if parent.get('arg'):argv+=['--build-arg',parent['arg']+'='+alias]
    subprocess.run(argv+[str(ctx)],check=True);image=(ctx/'image.id').read_text().strip()
    verify_child(image,base_info,output)
  health=json.loads(output(['docker','run','--rm','--network','none','--cpus','2','--memory','2g','--shm-size','256m',image,'python','-I','/opt/sweclar/preflight.py']))
  if health.get('passed') is not True:raise SystemExit('Environment preflight failed')
  record={'image':image,'platform':'linux/amd64','recipe_subdirectory':'amd64/'+name,'recipe_hashes':fingerprint,'preflight':health,'base_image':base}
  record_path.write_text(json.dumps(record,indent=2)+'\n');records[name]=record;print(json.dumps({'profile':name,'passed':True}),flush=True);return record
 for name in order:prepare(name)
if __name__=='__main__':main()
