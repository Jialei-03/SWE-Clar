import os,sys,runpy
assert os.getuid()==1000
assert int(next(x.split()[1] for x in open('/proc/self/status') if x.startswith('CapEff:')),16)==0
assert 'REGISTRATION_PRIVATE_SENTINEL' not in os.environ
sys.path.insert(0,os.path.dirname(sys.argv[1]))
runpy.run_path(sys.argv[1],run_name='__main__')
