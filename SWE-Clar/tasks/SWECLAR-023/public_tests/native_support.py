"""Prepared native build execution; candidate makefiles/programs never run as manager."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PUBLIC=Path(__file__).resolve().parent

def identity():
    return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}

def run(args,cwd,timeout=60,extra_env=None):
    env=dict(os.environ,HOME=str(cwd),UBSAN_OPTIONS='halt_on_error=1')
    env.update(extra_env or {})
    return subprocess.run(list(map(str,args)),cwd=cwd,env=env,text=True,capture_output=True,timeout=timeout,**identity())


def read_artifact(project,path):
    relative=Path(path).relative_to(project.path)
    if not relative.parts or any(part in ('.','..') for part in relative.parts):
        raise ValueError('Artifact path must stay within the candidate work tree')
    script="""import base64,os,stat,sys
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
 for part in sys.argv[2:-1]:
  next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
  os.close(fd);fd=next_fd
 leaf=os.open(sys.argv[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
 with os.fdopen(leaf,'rb') as handle:
  if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):raise ValueError('Artifact must be a regular file')
  print(base64.b64encode(handle.read()).decode('ascii'))
finally:os.close(fd)
"""
    result=run([sys.executable,'-I','-c',script,project.path,*relative.parts],project.path)
    assert result.returncode==0,'Candidate artifact cannot be read under candidate identity: '+result.stderr[-1600:]
    return base64.b64decode(result.stdout.strip(),validate=True)

class Project:
    def __init__(self,source=None):
        self.root=Path(tempfile.mkdtemp(prefix='graph-session-'));self.root.chmod(0o755)
        self.path=self.root/'work';shutil.copytree(source or os.environ.get('SWECLAR_PROJECT_DIR','/workspace'),self.path,ignore=shutil.ignore_patterns('build','.git','__pycache__','*.pyc','data'))
        if os.geteuid()==0:
            for p in [*self.path.rglob('*'),self.path]:
                if p.is_symlink():raise ValueError('Candidate symlink requires containment review')
                os.chown(p,1000,1000)
    def build(self,sanitized=False):
        self.flags=['-std=c11','-O1','-g','-Wall','-Wextra']+(['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if sanitized else [])
        clean=run(['make','clean'],self.path);assert clean.returncode==0,clean.stderr
        result=run(['make','all','CFLAGS='+' '.join(self.flags),'LDFLAGS='+('-fsanitize=address,undefined' if sanitized else '')],self.path)
        assert result.returncode==0,result.stderr
        assert (self.path/'build/libfcb_graph.a').is_file()
        return result
    def driver(self,source,name='public-driver'):
        output=self.path/'build'/name
        result=run(['cc',*self.flags,'-I'+str(self.path/'include'),source,self.path/'build/libfcb_graph.a','-o',output],self.path)
        assert result.returncode==0,result.stderr
        return output
    def execute(self,args):
        result=run(args,self.path)
        assert result.returncode==0 and not result.stderr,result
        return result.stdout
    def __enter__(self):return self
    def __exit__(self,*_):
        if os.geteuid()==0:
            subprocess.run([sys.executable,'-I','-c',"import pathlib,shutil,sys;p=pathlib.Path(sys.argv[1]);[(shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()) for x in p.iterdir()]",str(self.path)],check=True,**identity())
        shutil.rmtree(self.root)
