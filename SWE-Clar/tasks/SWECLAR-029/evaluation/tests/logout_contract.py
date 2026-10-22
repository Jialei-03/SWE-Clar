import os,subprocess,tempfile
from pathlib import Path
from contract_support import call,raw_call,read_as_user,identity
from auth_contract import auth

def metadata_file(meta):
 # The public contract specifies a root-relative file path, not its key name.
 value=meta.get('file',meta.get('path')) if isinstance(meta,dict) else None
 assert isinstance(value,str)
 return value

def check():
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);root.chmod(0o755);data=root/'bundles';data.mkdir();os.chown(data,1000,1000)
  try:
   config={'root':str(data),'key_hex':os.urandom(32).hex()};metadata={}
   for user in ['u','v']:
    result=raw_call({'operation':'write_bundle','store':config,'user_id':user,'job_id':'j','data':{'synthetic':user}});assert result['ok'],result;metadata[user]=result['result']
   preserved=read_as_user(data/metadata_file(metadata['v']))
   state=auth();state['offline']={u:{'j':meta} for u,meta in metadata.items()}
   state['sessions']['v']={'last_active':0}
   state['queue']=[{'action_id':'u-pending','user_id':'u','status':'pending'},{'action_id':'v-pending','user_id':'v','status':'pending'}]
   state['last_up']=7;state['last_down']=8
   status=call(state,{'type':'status'},config)['result'];assert status['last_up']==7 and status['last_down']==8 and status['pending']==2
   folder=(data/metadata_file(metadata['u'])).parent
   subprocess.run(['python','-I','-c','import os,sys;os.chmod(sys.argv[1],0o500)',str(folder)],check=True,**identity)
   try:
    failed=call(state,{'type':'logout','user_id':'u','now':1},config)
    assert failed['error']['code']=='logout_failed' and 'u' in failed['sessions']
   finally:subprocess.run(['python','-I','-c','import os,sys;os.chmod(sys.argv[1],0o700)',str(folder)],check=True,**identity)
   out=call(state,{'type':'logout','user_id':'u','now':1},config)
   assert 'u' not in out['sessions'] and 'u' not in out['offline']
   assert out['sessions']['v']==state['sessions']['v'] and out['offline']['v']==state['offline']['v']
   assert out['queue']==[state['queue'][1]]
   query='import pathlib,sys;assert not pathlib.Path(sys.argv[1]).exists()'
   subprocess.run(['python','-I','-c',query,str(data/metadata_file(metadata['u']))],check=True,**identity)
   assert read_as_user(data/metadata_file(metadata['v']))==preserved
  finally:
   subprocess.run(['python','-I','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]',str(data)],check=True,**identity)
