"""Public line transport to an unprivileged executable linked to candidate C ABI."""
import json
import os
import selectors
import subprocess
import tempfile
from native_support import PUBLIC,identity

def encode(value):
    if value is None:return '-'
    raw=value if isinstance(value,bytes) else value.encode('utf-8')
    return raw.hex() or '='

def decode(value):return None if value is None else bytes.fromhex(value).decode('utf-8')

class Bridge:
    def __init__(self,project):
        self.project=project;self.binary=project.driver(PUBLIC/'abi_bridge.c','abi-bridge')
        self.errors=tempfile.TemporaryFile(mode='w+t')
        self.process=subprocess.Popen([str(self.binary)],cwd=project.path,env=dict(os.environ,HOME=str(project.path),UBSAN_OPTIONS='halt_on_error=1'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,text=True,bufsize=1,**identity())
        self.selector=selectors.DefaultSelector();self.selector.register(self.process.stdout,selectors.EVENT_READ)
    def call(self,operation,*args):
        assert self.process.poll() is None,'Native process already exited'
        self.process.stdin.write(' '.join([operation,*map(str,args)])+'\n');self.process.stdin.flush()
        assert self.selector.select(20),'Native response timeout'
        line=self.process.stdout.readline()
        if not line:
            self.errors.seek(0);raise AssertionError('Native process ended: '+self.errors.read()[-2000:])
        value=json.loads(line)
        assert not isinstance(value,dict) or not value.get('transport_error'),'Invalid bridge protocol command'
        return value
    def __enter__(self):return self
    def __exit__(self,kind,*_):
        try:
            if self.process.poll() is None:
                if kind is None:self.call('quit')
                self.process.stdin.close()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.errors.seek(0);diagnostics=self.errors.read()
            if kind is None:assert self.process.returncode==0 and not diagnostics,diagnostics
        finally:
            self.selector.close();self.process.stdout.close();self.errors.close()
