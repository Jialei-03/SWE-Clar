import json,sys,traceback,tempfile,socket,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from auth_contract import check as auth_check
from storage_contract import check as storage_check
from sync_contract import check as sync_check
from logout_contract import check as logout_check

def infrastructure_check():
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 with tempfile.TemporaryDirectory() as directory:
  path=Path(directory)/'probe';key=os.urandom(32);nonce=os.urandom(12)
  path.write_bytes(AESGCM(key).encrypt(nonce,b'health',b'fixture'))
  assert AESGCM(key).decrypt(nonce,path.read_bytes(),b'fixture')==b'health'
 with socket.socket() as sock:sock.bind(('127.0.0.1',0))

def main():
 try:infrastructure_check()
 except Exception as error:return {'harness_ok':False,'results':[],'infrastructure_errors':[type(error).__name__+': '+str(error)]}
 results=[]
 checks=[lambda:auth_check(1),lambda:auth_check(2),storage_check,sync_check,logout_check]
 for gate,check in enumerate(checks,1):
  try:check();results.append({'ru_id':f'RU-{gate:03d}','passed':True})
  except Exception as error:results.append({'ru_id':f'RU-{gate:03d}','passed':False,'detail':traceback.format_exc()[-2400:]})
 return {'harness_ok':True,'results':results}
if __name__=='__main__':print(json.dumps(main()))
