"""Standard-library password helper. Never log passwords or encoded credentials."""
import hashlib,hmac,secrets

def hash_password(password):
 salt=secrets.token_hex(16);count=120000
 digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),count).hex()
 return f'pbkdf2_sha256${count}${salt}${digest}'

def verify_password(password,encoded):
 try:
  algorithm,count,salt,digest=encoded.split('$')
  if algorithm!='pbkdf2_sha256' or int(count)<100000 or not isinstance(password,str):return False
  return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(count)).hex(),digest)
 except (ValueError,TypeError,AttributeError):return False
