"""Public operation transport. Business expectations belong to callers, not this adapter."""
import base64,json,os,pathlib,shutil,subprocess,sys,tempfile
HERE=pathlib.Path(__file__).resolve().parent

class CandidateFailure(AssertionError):pass

COPY_PROJECT='''import pathlib,shutil,sys
source=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2])
shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','.dart_tool','build','.maintenance-output','__pycache__'))
'''
READ_FILE='''import base64,json,pathlib,sys
p=pathlib.Path(sys.argv[1]);data=p.read_bytes()
if len(data)>16*1024*1024:raise ValueError('Observation file exceeds 16 MiB')
print(base64.b64encode(data).decode())
'''


def run_session(operations,origin='http://127.0.0.1:8080',project=None):
    project=pathlib.Path(project or os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd())).resolve()
    driver=HERE/'maintenance_driver_test.dart'
    if not driver.is_file():raise RuntimeError('Prepared public Flutter operation adapter is missing')
    identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    root=pathlib.Path(tempfile.mkdtemp(prefix='sweclar-maintenance-'));os.chmod(root,0o755)
    environment={'PATH':os.environ['PATH'],'HOME':str(root/'home'),'CI':'true'}
    logs=[]
    def child(command,timeout=60,cwd=None):
        try:
            result=subprocess.run(command,cwd=cwd,env=environment,**identity,capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise CandidateFailure('Candidate operation did not finish within the published execution limit') from error
        logs.append({'command':command,'returncode':result.returncode,'stdout':result.stdout[-5000:],'stderr':result.stderr[-5000:]})
        if result.returncode:
            raise CandidateFailure('Candidate command failed: '+str(command)+'\n'+(result.stdout+result.stderr)[-3000:])
        return result.stdout
    def read(path):
        return base64.b64decode(child([sys.executable,'-I','-c',READ_FILE,str(path)],timeout=10).strip(),validate=True)
    try:
        (root/'home').mkdir();(root/'captures').mkdir();(root/'operations.json').touch()
        if identity:
            os.chown(root,1000,1000);os.chown(root/'home',1000,1000);os.chown(root/'captures',1000,1000)
        # All candidate material is opened/copied as its unprivileged identity.
        child([sys.executable,'-I','-c',COPY_PROJECT,str(project),str(root/'project')],timeout=20)
        commands=json.loads(json.dumps(operations));captures=[]
        for operation in commands:
            if operation.get('op')=='capture':
                name=operation.get('name')
                if not isinstance(name,str) or pathlib.Path(name).name!=name or not name.endswith('.png') or name in captures:
                    raise ValueError('Each capture requires a distinct basename ending in .png')
                captures.append(name);operation['path']=str(root/'captures'/name)
        (root/'operations.json').write_text(json.dumps({'origin':origin,'operations':commands}))
        environment.update(MAINTENANCE_OPERATIONS=str(root/'operations.json'),MAINTENANCE_OBSERVATIONS=str(root/'observations.json'))
        child(['flutter','pub','get','--offline','--enforce-lockfile'],cwd=root/'project')
        child(['flutter','test','--no-pub','--reporter','expanded',str(driver)],cwd=root/'project',timeout=90)
        try:
            data=json.loads(read(root/'observations.json'));rows=data['observations']
            if not isinstance(rows,list) or len(rows)!=len(commands):raise ValueError('Incomplete operation observations')
            for operation,row in zip(commands,rows):
                if row.get('op')!=operation['op']:raise ValueError('Operation order changed')
                if 'operation_error' in row:raise CandidateFailure('Candidate operation failed: '+row['operation_error'])
                if row.get('render_errors'):raise CandidateFailure('Flutter render failed: '+str(row['render_errors']))
            files={name:base64.b64encode(read(root/'captures'/name)).decode() for name in captures}
        except (KeyError,ValueError,TypeError) as error:
            raise CandidateFailure('Candidate session produced malformed observations: '+str(error)) from error
        return {'observations':rows,'captures_base64':files,'logs':logs}
    finally:
        # Copy/cache metadata can be private to UID 1000, so clean as that identity.
        subprocess.run([sys.executable,'-I','-c','import shutil,sys; shutil.rmtree(sys.argv[1])',str(root)],env=environment,**identity,capture_output=True,check=True)

# Each test session gets a separate real database and service process. The development
# endpoint and its records remain untouched by this context manager.
import contextlib,runpy

@contextlib.contextmanager
def isolated_database():
    service=runpy.run_path('/opt/sweclar/firestore_service.py')
    root=pathlib.Path(tempfile.mkdtemp(prefix='sweclar-maintenance-db-'));os.chmod(root,0o755)
    try:
        with service['session'](root/'server') as origin:
            yield service,origin
    finally:
        home=root/'server/home'
        if home.exists():
            os.chmod(home.parent,0o777)
            identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
            subprocess.run([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(home)],**identity,check=True,capture_output=True)
        shutil.rmtree(root)
