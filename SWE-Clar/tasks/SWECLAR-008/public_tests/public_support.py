"""Public local server/HTTP support. No private rules or expected answers are embedded."""
import contextlib,json,os,pathlib,runpy,sqlite3,tempfile,urllib.request,urllib.error
App=runpy.run_path('/opt/sweclar/harness.py')['App']
CandidateFailure=runpy.run_path('/opt/sweclar/harness.py')['CandidateFailure']


def request(app,path,token=None,body=None,method='GET',status=200,raw=False):
    headers={'Authorization':'Bearer '+token} if token else {}
    if body is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(app.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
    try:response=urllib.request.urlopen(req,timeout=10)
    except urllib.error.HTTPError as error:response=error
    except (OSError,TimeoutError) as error:raise CandidateFailure('Candidate HTTP operation failed: '+str(error)) from error
    with response:
        data=response.read()
        if response.status!=status:raise CandidateFailure(f'HTTP {response.status} instead of {status} for {path}: '+data.decode(errors='replace')[:300])
    if raw:return data.decode()
    try:return json.loads(data)
    except ValueError as error:raise CandidateFailure('Candidate did not return valid JSON') from error


@contextlib.contextmanager
def application(fixture,project=None):
    with tempfile.TemporaryDirectory(prefix='monitoring-fixture-') as directory:
        os.chmod(directory,0o755);source=pathlib.Path(directory)/'input.json';source.write_text(json.dumps(fixture));source.chmod(0o644)
        with App(project or os.environ.get('SWECLAR_PROJECT_DIR',os.getcwd()),['--fixtures',str(source)]) as app:yield app


def database_rows(app,table):
    """Read documented data as the database owner, including valid private file modes."""
    import subprocess,sys
    if table not in {'events','rules'}:raise ValueError('Only public business tables are supported')
    script='import json,sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.row_factory=sqlite3.Row; print(json.dumps([dict(r) for r in db.execute("SELECT * FROM "+sys.argv[2])]))'
    identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    try:
        result=subprocess.run([sys.executable,'-I','-c',script,str(app.db),table],env={'PATH':os.environ['PATH']},**identity,capture_output=True,text=True,timeout=15)
        if result.returncode:raise CandidateFailure('Candidate database could not be independently read: '+result.stderr[-500:])
        return json.loads(result.stdout)
    except (ValueError,subprocess.TimeoutExpired) as error:raise CandidateFailure('Invalid candidate database observation') from error
