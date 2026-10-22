"""Public build/browser support. Candidate Python runs only in a separate unprivileged process."""
from pathlib import Path
import json,os,select,shutil,subprocess,sys,tempfile

class CandidateFailure(AssertionError):pass

class Site:
    def __init__(self,project='/workspace'):
        self.project=Path(project);self.temp=tempfile.TemporaryDirectory(prefix='campaign-check-');self.root=Path(self.temp.name);self.root.chmod(0o777)
        self.work=self.root/'source';self.outputs=self.root/'outputs';self.outputs.mkdir();self.outputs.chmod(0o777)
        self.identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {};self.servers=[];self.serial=0
    def __enter__(self):
        try:
            if any(p.is_symlink() for p in self.project.rglob('*')):raise CandidateFailure('Source symlinks are not allowed')
            shutil.copytree(self.project,self.work,ignore=shutil.ignore_patterns('.git','site','__pycache__'))
            if os.getuid()==0:
                for p in [self.work,*self.work.rglob('*')]:os.chown(p,1000,1000)
            self.spec=json.loads((self.work/'spec.json').read_text());return self
        except BaseException:self.__exit__(None,None,None);raise
    def command(self,code,*args):
        r=subprocess.run([sys.executable,'-I','-c',code,*map(str,args)],cwd=self.work,capture_output=True,text=True,timeout=20,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        if r.returncode:raise CandidateFailure('Candidate file operation failed: '+r.stderr[-1500:])
        return r.stdout
    def build(self,spec,output=None,cli=False,assets=None):
        if output is None:self.serial+=1;output=self.outputs/('site-'+str(self.serial))
        assets=assets or self.work/'assets'
        code="""import contextlib,importlib.util,json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root));module=importlib.util.spec_from_file_location('candidate',root/'solution.py');candidate=importlib.util.module_from_spec(module)
with contextlib.redirect_stdout(sys.stderr):
 module.loader.exec_module(candidate);payload=json.load(sys.stdin);result=candidate.build_campaign_site(payload,sys.argv[2],sys.argv[3])
print(json.dumps({'result':result,'input_after':payload}))
"""
        args=[sys.executable,'-I',str(self.work/'solution.py'),str(output),str(assets)] if cli else [sys.executable,'-I','-c',code,str(self.work),str(output),str(assets)]
        r=subprocess.run(args,cwd=self.work,input=json.dumps(spec),capture_output=True,text=True,timeout=20,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        if r.returncode:raise CandidateFailure('Builder failed: '+r.stderr[-1500:])
        try:response=json.loads(r.stdout)
        except ValueError as error:raise CandidateFailure('Builder returned invalid JSON') from error
        if cli:result=response
        else:
            assert isinstance(response,dict) and response.get('input_after')==spec,'Builder mutated input'
            result=response.get('result')
        assert isinstance(result,dict),'Build result must be an object'
        return output,result
    def files(self,root):
        code="""from pathlib import Path
import base64,json,sys
root=Path(sys.argv[1]);rows={}
if root.exists():
 for p in root.rglob('*'):
  if p.is_symlink():raise AssertionError('Output symlink is forbidden')
  if p.is_file():rows[str(p.relative_to(root))]=base64.b64encode(p.read_bytes()).decode()
print(json.dumps(rows,sort_keys=True))
"""
        return json.loads(self.command(code,root))
    def serve(self,output):
        self.files(output)
        code="""from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import functools,sys
class NoCache(SimpleHTTPRequestHandler):
 def end_headers(self):self.send_header('Cache-Control','no-store');super().end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(NoCache,directory=sys.argv[1]))
print(server.server_port,flush=True);server.serve_forever()
"""
        process=subprocess.Popen([sys.executable,'-I','-c',code,str(output)],cwd=self.work,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'});self.servers.append(process)
        if not select.select([process.stdout],[],[],10)[0]:raise CandidateFailure('Local site server unavailable')
        port=process.stdout.readline().strip()
        if not port.isdigit():raise CandidateFailure('Generated site not readable by candidate identity')
        return 'http://127.0.0.1:'+port
    def __exit__(self,*_):
        for process in self.servers:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            process.stdout.close()
        for path in [self.work,self.outputs]:
            if path.exists():subprocess.run([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(path)],check=True,**self.identity, env={'PATH':os.environ['PATH'],'HOME':'/tmp'})
        self.temp.cleanup()
