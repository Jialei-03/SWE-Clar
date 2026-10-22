import json,os,subprocess,tempfile,hashlib,copy,base64
from pathlib import Path
from contract_support import call,raw_call,read_as_user,identity
from auth_contract import auth
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def encoded(data):return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def no_key(value,key):
 text=json.dumps(value,ensure_ascii=False)
 assert key.hex() not in text and base64.b64encode(key).decode() not in text
 if isinstance(value,dict):
  for item in value.values():no_key(item,key)
 elif isinstance(value,list):
  assert value!=list(key)
  for item in value:no_key(item,key)

def metadata_file(meta):
 # The README requires a root-relative file path but deliberately does not
 # reserve a metadata key name.  Accept the two natural spellings while
 # retaining the path-safety assertion below.
 value=meta.get('file',meta.get('path')) if isinstance(meta,dict) else None
 assert isinstance(value,str)
 return value

def metadata(meta,payload,key):
 plain=encoded(payload)
 assert type(meta.get('size_bytes')) is int and meta['size_bytes']==len(plain)
 assert meta.get('encrypted') is True
 # Digest spelling is not fixed by RU-003; its required value is.
 assert hashlib.sha256(plain).hexdigest() in meta.values()
 path=Path(metadata_file(meta));assert not path.is_absolute() and '..' not in path.parts and path.parts
 assert payload['text'] not in json.dumps(meta,ensure_ascii=False),'Plaintext leaked into metadata'
 no_key(meta,key)

def denied_downloads(state,action,config,data):
 for changes,overrides in [({},dict(job_id='unassigned')),({},dict(job_id='missing')),({'online':False},{}),({'sessions':{}},{}),({},dict(now=1801))]:
  before=copy.deepcopy(state);before.update(changes)
  denied=call(before,dict(action,capacity_bytes=10000,**overrides),config)
  assert denied.get('error',{}).get('code')
  assert denied.get('offline',{})==before.get('offline',{}) and denied.get('last_down')==before.get('last_down')
  assert not list(data.iterdir()),'Unauthorized download wrote files'

def check():
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);root.chmod(0o755);data=root/'bundles';data.mkdir();os.chown(data,1000,1000)
  try:
   key=os.urandom(32);config={'root':str(data),'key_hex':key.hex()};payload={'text':'Synthetic 汉字','value':9};plain=encoded(payload)
   state=auth();state.update(online=True,assignments={'u':['j']},remote_jobs={'j':{'data':payload}})
   action={'type':'download','user_id':'u','job_id':'j','now':1,'capacity_bytes':len(plain)-1}
   denied=call(state,action,config)
   # The contract reserves authentication error names, not a capacity-error token.
   assert isinstance(denied.get('error',{}).get('code'),str) and denied['error']['code']
   assert denied.get('offline',{})==state.get('offline',{}) and denied.get('last_down')==state.get('last_down')
   assert not list(data.iterdir()),'Denied request wrote files'
   state['remote_jobs']['unassigned']={'data':{'text':'Other synthetic job'}}
   denied_downloads(state,action,config,data)
   out=call(state,dict(action,capacity_bytes=len(plain)),config);meta=out['offline']['u']['j']
   metadata(meta,payload,key);no_key(out,key)
   path=data/metadata_file(meta);assert path.resolve().is_relative_to(data.resolve())
   first=read_as_user(path);assert first[:3]==b'FS1' and plain not in first
   assert AESGCM(key).decrypt(first[3:15],first[15:],encoded(['u','j']))==plain
   read={'operation':'read_bundle','store':config,'user_id':'u','job_id':'j'}
   assert raw_call(read)['result']==payload
   again=call(out,dict(action,capacity_bytes=len(plain),now=2),config)
   metadata(again['offline']['u']['j'],payload,key);no_key(again,key)
   second=read_as_user(data/metadata_file(again['offline']['u']['j']));assert first[3:15]!=second[3:15]
   assert raw_call(dict(read,store=dict(config,key_hex=os.urandom(32).hex())))['ok'] is False
   for user,job in [('v','j'),('u','other')]:
    direct={'text':'Synthetic direct bundle 汉字','synthetic':'placeholder'}
    target=raw_call({'operation':'write_bundle','store':config,'user_id':user,'job_id':job,'data':direct})
    assert target['ok'];metadata(target['result'],direct,key)
    assert target['ok'];target_path=data/metadata_file(target['result']);assert target_path.resolve().is_relative_to(data.resolve())
    subprocess.run(['python','-I','-c','import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))',str(target_path),second.hex()],check=True,**identity)
    assert raw_call({'operation':'read_bundle','store':config,'user_id':user,'job_id':job})['ok'] is False
   corruption=second[:-1]+bytes([second[-1]^1]);code='import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))'
   subprocess.run(['python','-I','-c',code,str(data/metadata_file(again['offline']['u']['j'])),corruption.hex()],check=True,**identity)
   assert raw_call(read)['ok'] is False
  finally:
   subprocess.run(['python','-I','-c','import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]',str(data)],check=True,**identity)
