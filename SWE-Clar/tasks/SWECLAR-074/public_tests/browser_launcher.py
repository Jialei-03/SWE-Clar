#!/usr/bin/env python3
import os,sys,json
binary=os.environ.pop('CLARSWE_BROWSER_BINARY')
proof=os.environ.pop('CLARSWE_BROWSER_PROOF')
if os.getuid()==0:
 for arg in sys.argv[1:]:
  if arg.startswith('--user-data-dir='):os.chmod(arg.split('=',1)[1],0o777)
 os.setgroups([]);os.setgid(1000);os.setuid(1000)
assert os.getuid()==1000
cap=int(next(x.split()[1] for x in open('/proc/self/status') if x.startswith('CapEff:')),16)
assert cap==0
assert 'CONSOLE_PRIVATE_SENTINEL' not in os.environ
with open(proof,'w') as f:json.dump({'pid':os.getpid(),'uid':os.getuid(),'cap_eff':cap,'environment_keys':sorted(os.environ)},f)
os.execve(binary,[binary,*sys.argv[1:]],{'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp'})
