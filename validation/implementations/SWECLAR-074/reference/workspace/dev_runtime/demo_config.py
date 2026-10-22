import hashlib,json,sys
from pathlib import Path
salt=b'public-demo-salt'
Path(sys.argv[1]).write_text(json.dumps({'users':{'demo':{'name':'Local demo','salt':salt.hex(),'password_hash':hashlib.scrypt(b'demo-password',salt=salt,n=16384,r=8,p=1).hex()}},'locations':[],'tracks':[]}))
