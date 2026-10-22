"""Frozen AMD64 lock replay. Inputs are read-only; all assembly uses a temporary copy."""
from pathlib import Path
import copy,hashlib,json,shutil,subprocess,tarfile,tempfile,urllib.request,uuid
from contextlib import contextmanager
import extension_assembly

def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def output(argv):return subprocess.check_output(argv,text=True).strip()
@contextmanager
def pinned_base(base,inspect_output=None):
 inspect_output=inspect_output or output
 original=json.loads(inspect_output(['docker','image','inspect',base]))[0]
 if original['Architecture']!='amd64':raise ValueError('Base architecture mismatch')
 # A --iidfile build may have no repository tags. Removing its only temporary
 # tag deletes that image, breaking later siblings which use the recorded ID.
 # Retain a content-addressed build-cache tag; never retag a different image.
 if not original.get('RepoTags'):
  cache_tag='swe-clar-build-cache:'+original['Id'].removeprefix('sha256:')
  subprocess.run(['docker','tag',original['Id'],cache_tag],check=True)
  retained=json.loads(inspect_output(['docker','image','inspect',cache_tag]))[0]
  if retained['Id']!=original['Id']:raise ValueError('Build cache tag identity mismatch')
 alias='swe-clar-build-'+uuid.uuid4().hex+':base'
 subprocess.run(['docker','tag',original['Id'],alias],check=True)
 try:
  tagged=json.loads(inspect_output(['docker','image','inspect',alias]))[0]
  if tagged['Id']!=original['Id'] or tagged['RootFS']['Layers']!=original['RootFS']['Layers'] or tagged['Architecture']!='amd64':raise ValueError('Temporary base tag identity mismatch')
  yield alias,original
 finally:
  subprocess.run(['docker','image','rm',alias],check=True,capture_output=True)

def verify_child(image,parent,inspect_output=None):
 actual=json.loads((inspect_output or output)(['docker','image','inspect',image]))[0]
 if actual['Id']!=image or actual['Architecture']!='amd64' or actual['RootFS']['Layers'][:len(parent['RootFS']['Layers'])]!=parent['RootFS']['Layers']:raise ValueError('Derived image identity/layer mismatch')

def obtain(cache,row):
 if not row.get('sha256'):raise ValueError('Frozen artifact requires SHA256')
 dest=cache/row['sha256']
 if not dest.exists():
  with tempfile.NamedTemporaryFile(dir=cache,delete=False) as stream:
   tmp=Path(stream.name)
   try:
    with urllib.request.urlopen(row['url'],timeout=120) as response:shutil.copyfileobj(response,stream)
   except BaseException:tmp.unlink(missing_ok=True);raise
  try:
   if digest(tmp)!=row['sha256']:raise ValueError('Artifact checksum mismatch')
   tmp.replace(dest)
  finally:tmp.unlink(missing_ok=True)
 if digest(dest)!=row['sha256']:raise ValueError('Cached artifact checksum mismatch')
 if row.get('sha512'):
  with dest.open('rb') as f:
   if hashlib.file_digest(f,'sha512').hexdigest().lower()!=row['sha512'].lower():raise ValueError('SHA512 mismatch')
 # Verified public artifacts must remain readable by the unprivileged runtime.
 dest.chmod(0o644)
 return dest

def extract(archive,dest,strip=True):
 dest.mkdir(parents=True,exist_ok=True)
 with tarfile.open(archive) as t:
  if strip:
   with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
    stage=Path(tmp);t.extractall(stage,filter='data');items=list(stage.iterdir())
    if len(items)!=1 or not items[0].is_dir():raise ValueError('Archive requires one root directory')
    shutil.copytree(items[0],dest,dirs_exist_ok=True)
  else:t.extractall(dest,filter='data')

def npm(lock,dest):
 dest.mkdir(parents=True,exist_ok=True)
 for name in ('package.json','package-lock.json'):
  src=lock.parent/name
  if src.resolve()!=(dest/name).resolve():shutil.copy2(src,dest/name)
 for name,row in json.loads(lock.read_text())['packages'].items():
  if name and not (row.get('integrity','').startswith(('sha512-','sha256-')) and row.get('resolved','').startswith('https://registry.npmjs.org/')):raise ValueError('Unpinned npm artifact: '+name)
 subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund','--prefix',str(dest)],check=True)

def blocked_metadata(*args):raise ValueError('Version discovery forbidden in frozen replay')
def stage_ocr_packages(context,lock,get):
 if lock.get('ocr_deb_packages'):
  folder=context/'ocr-packages';folder.mkdir(exist_ok=True)
  for row in lock['ocr_deb_packages']:
   if Path(row['filename']).name!=row['filename']:raise ValueError('OCR package filename must be a basename')
   shutil.copy2(get(row),folder/row['filename'])

def replay(root,name,lock,cache,base,hashes):
 recipe=root/'amd64'/name;before=hashes(recipe)
 with tempfile.TemporaryDirectory(prefix='swe-clar-extension-') as tmp:
  context=Path(tmp);shutil.copytree(recipe,context,dirs_exist_ok=True)
  frozen=copy.deepcopy(lock);old=copy.deepcopy(lock)
  text=(context/'Dockerfile').read_text();args=[]
  get=lambda row:obtain(cache,row)
  stage_ocr_packages(context,lock,get)
  def wheel(row):
   filename=row if isinstance(row,str) else row.get('filename')
   matches=[r for r in lock['wheels'] if r.get('filename')==filename]
   if len(matches)!=1:raise ValueError('Frozen wheel not found: '+str(filename))
   return dict(matches[0])
  wheel_profiles={'python-crypto','python-document-io','php-editable-doc','python-game','python-media-score','php-document','php-wordpress','dotnet-sql','python-comfy'}
  if name in wheel_profiles:
   folder=context/('wheelhouse' if name in {'python-game','php-document'} else 'wheels');folder.mkdir(exist_ok=True)
   for row in lock['wheels']:shutil.copy2(get(row),folder/row['filename'])
  if name in {'node-sdk','node-websocket','flutter-websocket'}:npm(context/'package-lock.json',context/('sdk' if name=='node-sdk' else 'modules'))
  if name=='python-cesium':extract(get(lock['archives'][0]),context/'cesium')
  # Assembly modifies its private copies only. The AMD64 lock is already architecture resolved.
  text,args=extension_assembly.assemble(name,old,frozen,context,context,text,{'obtain':get,'extract':extract,'npm':npm,'getjson':blocked_metadata,'cache':cache,'original':context,'wheel':wheel})
  # Pull frozen multi-stage images before entering the offline build.
  for line in text.splitlines():
   words=line.split()
   if len(words)>1 and words[0].upper()=='FROM' and '@sha256:' in words[1]:
    subprocess.run(['docker','pull','--platform','linux/amd64',words[1]],check=True)
  with pinned_base(base) as (alias,parent):
   text=text.replace('swe-clar-base-python-classroom:locked',alias)
   text='\n'.join(('FROM '+alias+line[len('FROM '+base):]) if line.startswith('FROM '+base) else line for line in text.splitlines())+'\n'
   (context/'Dockerfile').write_text(text)
   argv=['docker','build','--platform','linux/amd64','--network','none','--pull=false','--build-arg','BASE_IMAGE='+alias,'--build-arg','WEB_IMAGE='+alias,*args,'--iidfile',str(context/'image.id'),str(context)]
   subprocess.run(argv,check=True);image=(context/'image.id').read_text().strip()
   verify_child(image,parent)
  health=json.loads(output(['docker','run','--rm','--network','none','--cpus','2','--memory','7g' if name=='python-comfy' else '2g','--shm-size','256m',image,'python','-I','/opt/sweclar/preflight.py']))
  if health.get('passed') is not True:raise ValueError('Environment preflight failed')
 if hashes(recipe)!=before:raise ValueError('Recipe unexpectedly modified')
 return {'image':image,'platform':'linux/amd64','recipe_subdirectory':'amd64/'+name,'recipe_hashes':before,'preflight':health,'base_image':base}

def profile_order(root,names):
 done=[];visiting=set()
 def visit(name):
  if not isinstance(name,str) or name not in {p.name for p in (root/'amd64').iterdir() if p.is_dir()}:raise ValueError('Unknown profile')
  if name in done:return
  if name in visiting:raise ValueError('Profile dependency cycle')
  visiting.add(name);lock=json.loads((root/'amd64'/name/'lock.json').read_text());parent=lock.get('base',{}).get('profile',lock.get('base_profile'))
  if parent:visit(parent)
  visiting.remove(name);done.append(name)
 for name in names:visit(name)
 return done
