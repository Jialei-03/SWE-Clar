"""Additional source-locked AMD64 artifact assembly; imported by the profile builder."""
import copy,hashlib,importlib.util,json,re,shutil,subprocess,sys,tarfile,urllib.request,urllib.parse,zipfile
from pathlib import Path
WORDPRESS='wordpress@sha256:362e268b6a8d69c1f2384cd0a4be4de9bf0f02d8349a1a37e1cd30352a26abf7'
MARIADB='mariadb@sha256:ec1794c8cd442f795b838f60379d7851acf8fef04cc39a8ecf74e7b1d6a3b6d7'
GCC='gcc@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c'
def pull(ref):subprocess.run(['docker','pull','--platform','linux/amd64',ref],check=True);return ref
def assemble(name,old,lock,recipe,context,text,api):
 obtain,extract,npm,getjson,cache=api['obtain'],api['extract'],api['npm'],api['getjson'],api['cache'];args=[]
 if name=='python-media':
  tools=context/'tools';licenses=context/'licenses';tools.mkdir();licenses.mkdir()
  for row in lock['archives']:
   row=dict(row);component='ffmpeg' if 'ffmpeg' in row['filename'].lower() else 'mediamtx'
   archive=obtain(row);folder=context/(component+'-download');extract(archive,folder,strip=component=='ffmpeg')
   for binary in (['ffmpeg','ffprobe'] if component=='ffmpeg' else ['mediamtx']):
    source=next(p for p in folder.rglob(binary) if p.is_file());shutil.copy2(source,tools/binary);(tools/binary).chmod(0o755)
   for p in folder.rglob('*'):
    if p.is_file() and p.name.lower().startswith(('license','copying')):shutil.copy2(p,licenses/(component+'-'+p.name))
   shutil.rmtree(folder)
 elif name in ['python-media-score','python-portal']:
  npm(recipe/'ui/package-lock.json',context/'ui')
  if name=='python-portal':
   row=dict(lock['mongodb']);folder=context/'mongodb-download';extract(obtain(row),folder);(context/'tools').mkdir();shutil.copy2(folder/'bin/mongod',context/'tools/mongod');(context/'tools/mongod').chmod(0o755);(context/'licenses').mkdir()
   for f in folder.iterdir():
    if f.is_file():shutil.copy2(f,context/'licenses'/f.name)
   lock['mongodb']=row;shutil.rmtree(folder)
 elif name in ['php-document','php-wordpress','dotnet-sql']:
  if name in ['php-document','php-wordpress']:
   WORDPRESS=old['wordpress_image'];pull(WORDPRESS);args+=['--build-arg',('PHP_IMAGE=' if name=='php-document' else 'WORDPRESS_IMAGE=')+WORDPRESS];lock['wordpress_image']=WORDPRESS
  if name in ['php-wordpress','dotnet-sql']:
   MARIADB=old['database_image'];pull(MARIADB);args+=['--build-arg','DATABASE_IMAGE='+MARIADB];lock['database_image']=MARIADB
  if name=='php-document':
   row=dict(old['archives'][0]);shutil.copy2(obtain(row),context/'tcpdf.tar.gz')
  if name=='dotnet-sql':
   row=dict(lock['sdk']);f=obtain(row)
   with f.open('rb') as stream:assert hashlib.file_digest(stream,'sha512').hexdigest().lower()==row['sha512'].lower()
   shutil.copy2(f,context/'dotnet-sdk.tar.gz');lock['sdk']=row;(context/'nuget').mkdir()
   for row in old['nuget']:shutil.copy2(obtain(row),context/'nuget'/(row['name']+'.'+row['version']+'.nupkg'))
   lock['nuget']=old['nuget']
 elif name=='dotnet-sqlite':
  (context/'feed').mkdir()
  for row in old['packages']:shutil.copy2(obtain(row),context/'feed'/row['filename'])
  lock['packages']=old['packages']
 elif name=='native-wx':
  (context/'debs').mkdir();lock['packages']=[]
  for row in old['packages']:
   row=dict(row)
   f=obtain(row);arch=subprocess.check_output(['dpkg-deb','--field',str(f),'Architecture'],text=True).strip();assert arch in ['amd64','all'];shutil.copy2(f,context/'debs'/row['filename']);lock['packages'].append(row)
 elif name=='flutter-component':
  source=(Path(__file__).parent/'flutter_assembly.py').read_text();scope={'__file__':str(recipe/'prepare.py'),'__name__':'flutter_assembly'};exec(compile(source,str(recipe/'prepare.py'),'exec'),scope)
  flutter=copy.deepcopy(old['flutter']);flutter['platform']='linux/amd64';sdk_cache=cache/'flutter-amd64';sdk_cache.mkdir(exist_ok=True)
  for kind in ['sdk_artifacts','pub_artifacts']:
   for row in flutter[kind]:
    f=obtain(row);dest=sdk_cache/row['file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dest)
  scope['assemble'](sdk_cache,context,flutter);lock['flutter']=flutter
 elif name=='flutter-firestore':
  lock['artifacts']=copy.deepcopy(old['artifacts'])
  java,emulator=lock['artifacts']
  extract(obtain(java),context/'jre');shutil.copy2(obtain(emulator),context/'emulator.jar')
 elif name=='python-audio':
  pull(GCC);text=text.replace('sweclar-audio-base:locked',GCC);sdk=cache/'vst3sdk'
  if not sdk.exists():
   subprocess.run(['git','clone','--depth','1','--branch',old['sdk']['tag'],old['sdk']['url'],str(sdk)],check=True)
   subprocess.run(['git','-C',str(sdk),'submodule','update','--init','--depth','1',*old['sdk']['submodules']],check=True)
  for repo,commit,dest in [(sdk,old['sdk']['commit'],context/'sdk')]+[(sdk/n,c,context/'sdk'/n) for n,c in old['sdk']['submodules'].items()]:
   assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()==commit
   dest.mkdir(parents=True,exist_ok=True);archive=context/'git-source.tar'
   with archive.open('wb') as out:subprocess.run(['git','-C',str(repo),'archive',commit],stdout=out,check=True)
   with tarfile.open(archive) as t:t.extractall(dest,filter='data')
   archive.unlink()
  lock['wheels']=[api['wheel'](x) for x in old['wheels']]
  for row in lock['wheels']:
   f=obtain(row)
   if row['name']=='cmake':
    tmp=context/'cmake-wheel'
    with zipfile.ZipFile(f) as z:z.extractall(tmp)
    shutil.copytree(tmp/'cmake/data',context/'cmake');shutil.rmtree(tmp)
    for b in (context/'cmake/bin').iterdir():b.chmod(0o755)
   else:
    with zipfile.ZipFile(f) as z:z.extractall(context/'python_site')
  lock['sdk']=old['sdk'];lock['compiler_image']=GCC
 elif name=='python-classroom':
  pull(GCC);text=text.replace('sweclar-audio-base:locked',GCC).replace('sweclar-classroom-base:locked','swe-clar-base-python-classroom:locked')
  row=dict(old['archives'][0]);extract(obtain(row),context/'source')
  row=dict(old['archives'][1]);shutil.copy2(obtain(row),context/'ggml-tiny.en.bin')
  row=next(dict(row) for row in old['wheels'] if row['name']=='cmake');f=obtain(row);tmp=context/'cmake-wheel'
  with zipfile.ZipFile(f) as z:z.extractall(tmp)
  shutil.copytree(tmp/'cmake/data',context/'cmake');shutil.rmtree(tmp)
  for b in (context/'cmake/bin').iterdir():b.chmod(0o755)
  lock['wheels']=[row]
 elif name=='python-comfy':
  (context/'models').mkdir();(context/'licenses').mkdir()
  for i,row in enumerate(old['sources']):
   folder=context/('source'+str(i));extract(obtain(row),folder)
   if i==0:folder.rename(context/'comfy')
   else:
    dest=context/'comfy/custom_nodes/ipadapter';dest.mkdir()
    for f in folder.iterdir():
     if f.is_file() and (f.suffix=='.py' or f.name in ['LICENSE','README.md','NODES.md']):shutil.copy2(f,dest/f.name)
    shutil.rmtree(folder)
  spec=importlib.util.spec_from_file_location('ip_patch',recipe/'patch_ipadapter.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.apply(context/'comfy/custom_nodes/ipadapter/CrossAttentionPatch.py')
  installed={'checkpoints':'v1-5-pruned-emaonly-fp16.safetensors','controlnet':'control-canny-fp16.safetensors','clip_vision':'ViT-H-fp16.safetensors','ipadapter':'ip-adapter-plus-face_sd15.safetensors'}
  for row in old['models']:
   folder=context/'models'/row['install_folder'];folder.mkdir();dest=folder/installed[row['install_folder']];source=obtain(row)
   if row['install_folder']=='clip_vision':
    conversion=json.loads(subprocess.check_output([sys.executable,str(recipe/'convert_f16.py'),str(source),str(dest)],text=True));assert conversion==old['precision_conversion']
   else:shutil.copy2(source,dest)
  for row in old['documents']:shutil.copy2(obtain(row),context/'licenses'/row['filename'])
  (context/'licenses/provenance.json').write_text(json.dumps({'models':old['models'],'precision_conversion':old['precision_conversion']},indent=2));lock.update({k:old[k] for k in ['models','sources','documents','precision_conversion']})
 if name=='python-calendar' and 'XDG_CONFIG_HOME' not in text:
  text+='\nENV HOME=/tmp XDG_CONFIG_HOME=/tmp/sweclar-browser-config XDG_CACHE_HOME=/tmp/sweclar-browser-cache\n'
 return text,args
