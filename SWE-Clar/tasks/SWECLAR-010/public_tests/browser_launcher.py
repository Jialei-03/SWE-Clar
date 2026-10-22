#!/usr/bin/env python3
"""Execute Chromium as the ordinary candidate identity with a minimal environment."""
import json,os,sys
from pathlib import Path
binary=os.environ['CLARSWE_BROWSER_BINARY'];proof=os.environ['CLARSWE_BROWSER_PROOF']
public_env={key:os.environ[key] for key in ['PATH','HOME']}
assert 'CLARSWE_PRIVATE_BROWSER_SENTINEL' not in os.environ
if os.getuid()==0:
    for arg in sys.argv[1:]:
        if arg.startswith('--user-data-dir='):
            path=Path(arg.split('=',1)[1])
            assert path.is_dir() and not path.is_symlink() and str(path).startswith('/tmp/')
            os.chown(path,1000,1000)
    os.setgroups([]);os.setgid(1000);os.setuid(1000)
assert os.getuid()==1000
cap=int(next(line.split()[1] for line in open('/proc/self/status') if line.startswith('CapEff:')),16)
assert cap==0
with open(proof,'w') as out:json.dump({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':cap,'environment_keys':sorted(public_env),'private_sentinel_absent':True},out)
os.execve(binary,[binary,*sys.argv[1:]],public_env)
