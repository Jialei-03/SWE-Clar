import json,os,tempfile
from pathlib import Path
import cryptography
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
assert os.getuid()==1000
key=os.urandom(32);nonce=os.urandom(12);cipher=AESGCM(key)
with tempfile.TemporaryDirectory() as folder:
 p=Path(folder)/'bundle';p.write_bytes(nonce+cipher.encrypt(nonce,b'synthetic offline bundle',b'fixture-user/job'))
 data=p.read_bytes();assert AESGCM(key).decrypt(data[:12],data[12:],b'fixture-user/job')==b'synthetic offline bundle'
 for blob,aad in [(data[:-1]+bytes([data[-1]^1]),b'fixture-user/job'),(data,b'other-user/job')]:
  try:cipher.decrypt(blob[:12],blob[12:],aad)
  except InvalidTag:pass
  else:raise AssertionError('Authentication failed to reject alteration')
print(json.dumps({'passed':True,'cryptography':cryptography.__version__,'candidate_uid':os.getuid(),'real_file_roundtrip':True,'tamper_and_identity_mismatch_rejected':True}))
