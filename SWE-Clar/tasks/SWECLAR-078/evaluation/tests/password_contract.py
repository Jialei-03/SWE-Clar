"""Independent verification of the explicitly disclosed stdlib KDF boundary.

Recompute the stored verifier, never trust candidate-reported KDF calls. This
qualifies the bounded encodings/profiles in README, not arbitrary secure KDFs.
"""
import base64
import hashlib
import hmac
import json
import unicodedata

def decode_bytes(value,encoding):
    assert isinstance(value,str)
    if encoding=='hex':return bytes.fromhex(value)
    assert encoding in ('base64','base64url')
    value+='='*(-len(value)%4)
    return base64.b64decode(value,altchars=b'-_' if encoding=='base64url' else None,validate=True)

def assert_password_verifier(encoded,password):
    assert isinstance(encoded,str) and isinstance(password,str)
    if encoded.lstrip().startswith('{'):
        # Reject duplicate keys instead of hiding data in a discarded value.
        def unique(pairs):
            result={}
            for key,value in pairs:
                assert key not in result
                result[key]=value
            return result
        data=json.loads(encoded,object_pairs_hook=unique)
    else:
        parts=encoded.split('$')
        if parts[0] in ('pbkdf2_sha256','pbkdf2_sha512'):
            assert len(parts)==4
            kind,cost,salt,digest=parts
            data={'kdf':'pbkdf2','hash':kind.removeprefix('pbkdf2_'),'iterations':int(cost),'salt':salt,'digest':digest}
        else:
            assert len(parts)==6 and parts[0]=='scrypt'
            _,n,r,p,salt,digest=parts
            data={'kdf':'scrypt','n':int(n),'r':int(r),'p':int(p),'salt':salt,'digest':digest}
    common={'kdf','salt','digest','encoding','prehash','normalization'}
    kind=data.get('kdf')
    assert kind in ('pbkdf2','scrypt')
    assert set(data)<=common|({'hash','iterations'} if kind=='pbkdf2' else {'n','r','p'})
    encoding=data.get('encoding','hex')
    salt=decode_bytes(data['salt'],encoding);digest=decode_bytes(data['digest'],encoding)
    assert len(salt)>=16 and 32<=len(digest)<=64
    normalization=data.get('normalization','none');assert normalization in ('none','NFC','NFKC')
    raw=(password if normalization=='none' else unicodedata.normalize(normalization,password)).encode('utf-8')
    prehash=data.get('prehash','none');assert prehash in ('none','sha256','sha512')
    if prehash!='none':raw=hashlib.new(prehash,raw).digest()
    if kind=='pbkdf2':
        count=data['iterations'];algorithm=data['hash']
        assert type(count) is int and 100000<=count<=1000000 and algorithm in ('sha256','sha512')
        expected=hashlib.pbkdf2_hmac(algorithm,raw,salt,count,dklen=len(digest))
    else:
        n,r,p=[data[key] for key in ('n','r','p')]
        assert all(type(v) is int for v in (n,r,p))
        assert n in (16384,32768,65536) and r==8 and 1<=p<=4
        expected=hashlib.scrypt(raw,salt=salt,n=n,r=r,p=p,dklen=len(digest),maxmem=128*1024*1024)
    assert hmac.compare_digest(expected,digest),'Stored verifier is not the declared password derivation'
