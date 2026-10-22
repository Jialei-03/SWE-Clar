"""Native capability checks before budget, never imports candidate sources."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_support import run

SOURCE=r'''
#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/resource.h>
int main(void){struct timespec a,b;struct rusage r;char *p=malloc(64);if(!p)return 2;p[63]=7;free(p);if(clock_gettime(CLOCK_MONOTONIC,&a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&b)||getrusage(RUSAGE_SELF,&r))return 3;puts("prepared");return 0;}
'''
def preflight():
    with tempfile.TemporaryDirectory(prefix='graph-preflight-') as tmp:
        p=Path(tmp)
        source=p/'probe.c';source.write_text(SOURCE);source.chmod(0o444)
        bad_source=p/'bad.c';bad_source.write_text('int main(void){volatile int i=4;int a[1]={0};return a[i];}\n');bad_source.chmod(0o444)
        p.chmod(0o755)
        if os.geteuid()==0:os.chown(p,1000,1000)
        flags=['-std=c11','-O1','-g','-Wall','-Wextra','-fsanitize=address,undefined','-fno-omit-frame-pointer']
        built=run(['cc',*flags,source,'-o',p/'probe'],p);assert built.returncode==0,built.stderr
        good=run([p/'probe'],p);assert good.returncode==0 and good.stdout.strip()=='prepared' and not good.stderr,good
        built=run(['cc',*flags,bad_source,'-o',p/'bad'],p);assert built.returncode==0,built.stderr
        bad=run([p/'bad'],p);assert bad.returncode!=0 and ('runtime error' in bad.stderr or 'AddressSanitizer' in bad.stderr),bad
        guard=run([sys.executable,'-I','-c',"import os,pathlib;assert os.getuid()==1000;assert not os.access('/private',os.R_OK);assert not os.access('/public_tests/test_graph.c',os.W_OK);assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0;print('isolated')"],p)
        assert guard.returncode==0,guard.stderr
        # UID1000 owns the temp directory; manager cannot remove its nonempty files without delegation.
        removed=run([sys.executable,'-I','-c',"import pathlib,sys;p=pathlib.Path(sys.argv[1]);[x.unlink() for x in p.iterdir()]",p],p);assert removed.returncode==0,removed.stderr
    return {'passed':True,'candidate_code_loaded':False,'candidate_uid':1000,'capabilities':0,'private_access_denied':True,'public_fixture_write_denied':True,'c11_compile_execute':True,'sanitizer_good_and_bad_verified':True,'monotonic_process_cpu_peak_rss':True,'native_tmp_execution':True}
if __name__=='__main__':print(json.dumps(preflight()))
