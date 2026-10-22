"""Protected evaluator. Candidate builds and services run only as UID 1000."""
from pathlib import Path
from contextlib import contextmanager
import base64,json,os,secrets,shutil,socket,ssl,subprocess,sys,tempfile,time,urllib.request,urllib.error
import pymysql
PUBLIC=Path('/public_tests')
sys.path.insert(0,str(PUBLIC))
from database_fixture import DatabaseFixture
from certificates import certificates
ROOT=Path(os.environ['SWECLAR_PROJECT_DIR']);DOTNET=shutil.which('dotnet');ACTIVE=None
IDS=['001_create_samples','002_add_category','003_index_category']
CANDIDATE_ENV={'PATH':os.environ['PATH'],'HOME':'/tmp','DOTNET_ROOT':'/opt/dotnet','NUGET_PACKAGES':'/opt/sweclar/nuget-cache','DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false','DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK':'1'}

def subset(body,expected):
    assert isinstance(body,dict)
    for key,value in expected.items():assert body.get(key)==value,(key,body.get(key),value)

def expect(response,status,expected):
    assert response[0]==status,response[0]
    subset(response[1],expected)

def connect(database=None):
    return pymysql.connect(unix_socket=ACTIVE.socket,user='root',password=ACTIVE.admin_password,database=database,autocommit=True)

def sql(db,query,params=None):
    with connect(db) as connection:
        with connection.cursor() as cursor:cursor.execute(query,params);return cursor.fetchall()

def seed_schema(db):
    sql(db,"CREATE TABLE samples (id VARCHAR(80) PRIMARY KEY,name VARCHAR(160) NOT NULL,category VARCHAR(80) NOT NULL DEFAULT 'general')")
    sql(db,'CREATE INDEX sample_category ON samples(category)')
    sql(db,'CREATE TABLE IF NOT EXISTS schema_migrations (sequence_id INT AUTO_INCREMENT PRIMARY KEY,migration_id VARCHAR(80) NOT NULL UNIQUE)')
    for migration in IDS:sql(db,'INSERT INTO schema_migrations (migration_id) VALUES (%s)',(migration,))

def context(certdir,client=None):
    ctx=ssl.create_default_context(cafile=str(certdir/'ca.pem'))
    if client:ctx.load_cert_chain(str(certdir/(client+'.pem')),str(certdir/(client+'.key')))
    return ctx

def request(base,ctx,method,path,body=None,headers=None):
    req=urllib.request.Request(base+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
    try:response=urllib.request.urlopen(req,context=ctx,timeout=4)
    except urllib.error.HTTPError as error:response=error
    with response:return response.status,json.loads(response.read())

@contextmanager
def server(binary,dbname,certdir,pfx_password,bad_password=False):
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    password=secrets.token_hex(24) if bad_password else ACTIVE.password
    connection=f'Server=127.0.0.1;Port={ACTIVE.port};User ID={ACTIVE.username};Password={password};Database={dbname};Connection Timeout=2;SslMode=Disabled'
    payload={name:base64.b64encode((certdir/name).read_bytes()).decode() for name in ['ca.pem','server.pfx']}
    script="import base64,json,tempfile;from pathlib import Path;p=Path(tempfile.mkdtemp(prefix='candidate-tls-'));[(p/n).write_bytes(base64.b64decode(v)) for n,v in json.load(__import__('sys').stdin).items()];print(p)"
    made=subprocess.run([sys.executable,'-I','-c',script],input=json.dumps(payload),text=True,capture_output=True,user=1000,group=1000,extra_groups=[],check=True)
    publiccert=Path(made.stdout.strip())
    env={**CANDIDATE_ENV,'MARIADB_CONNECTION':connection,'API_PORT':str(port),'SERVER_PFX':str(publiccert/'server.pfx'),'SERVER_PFX_PASSWORD':pfx_password,'CLIENT_CA_PEM':str(publiccert/'ca.pem')}
    base=f'https://127.0.0.1:{port}';ctx=context(certdir)
    with tempfile.TemporaryFile(mode='w+t') as log:
        process=subprocess.Popen([DOTNET,str(binary)],cwd=binary.parent,env=env,stdout=log,stderr=subprocess.STDOUT,user=1000,group=1000,extra_groups=[])
        try:
            deadline=time.monotonic()+15
            while True:
                if process.poll() is not None:raise AssertionError('Candidate API exited before serving HTTPS')
                try:
                    # Any HTTP response proves readiness; malformed health behavior is tested by its own gate.
                    try:response=urllib.request.urlopen(base+'/health',context=ctx,timeout=2)
                    except urllib.error.HTTPError as error:response=error
                    response.close();break
                except OSError:
                    if time.monotonic()>deadline:raise TimeoutError('Unattributed startup timeout; reproduce before scoring')
                    time.sleep(.05)
            yield base,ctx
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            subprocess.run([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(publiccert)],user=1000,group=1000,extra_groups=[],check=True)
def ru001(binary,db,certdir,password):
    with server(binary,db,certdir,password) as (base,ctx):
        status,body=request(base,ctx,'GET','/health')
        assert status==200 and body['tls_configured'] is True
        serialized=json.dumps(body)
        assert ACTIVE.password not in serialized and password not in serialized
        assert ACTIVE.connection_string not in serialized and 'PRIVATE KEY' not in serialized
        assert request(base,context(certdir,'client'),'GET','/health')[0]==200
        try:status,_=request(base,context(certdir,'untrusted'),'GET','/health')
        except (OSError,urllib.error.URLError,ssl.SSLError):pass
        else:assert status>=400

def ru002(binary,db,certdir,password):
    with server(binary,db,certdir,password) as (base,ctx):
        assert request(base,ctx,'POST','/connect',{'provider':'PostgreSQL','connection_ok':True})[0]>=400
        assert request(base,ctx,'POST','/connect',{'provider':'mariadb','connection_ok':False})[1]['connected'] is True
    with server(binary,db,certdir,password,bad_password=True) as (base,ctx):
        code,body=request(base,ctx,'POST','/connect',{'provider':'MariaDB','connection_ok':True})
        assert code>=400 and body['error']=='database_connection_failed'
        assert request(base,ctx,'GET','/health')[1]['database_connected'] is False

def ru003(binary,db,certdir,password):
    global ACTIVE
    with server(binary,db,certdir,password) as (base,ctx):
        assert sql(db,"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name='samples'",(db,))[0][0]==0
        expect(request(base,ctx,'POST','/migrations',IDS[:1]),200,{'applied':IDS[:1],'all':IDS[:1]})
        columns=sql(db,"SELECT COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,IS_NULLABLE,COLUMN_KEY FROM information_schema.columns WHERE table_schema=%s AND table_name='samples'",(db,))
        assert ('id','varchar',80,'NO','PRI') in columns and any(row[:4]==('name','varchar',160,'NO') for row in columns)
        sql(db,'INSERT INTO samples(id,name) VALUES (%s,%s)',('fresh-row','Fresh installation'))
        expect(request(base,ctx,'POST','/migrations',IDS),200,{'applied':IDS[1:],'all':IDS})
        assert sql(db,'SELECT name,category FROM samples WHERE id=%s',('fresh-row',))==(('Fresh installation','general'),)
    # Keep the independent interrupted-DDL scenario on another empty fixture.
    previous=ACTIVE
    try:
        with DatabaseFixture() as fixture:
            ACTIVE=fixture
            migration_resume(binary,fixture.database,certdir,password)
    finally:ACTIVE=previous

def migration_resume(binary,db,certdir,password):
    with server(binary,db,certdir,password) as (base,ctx):
        for ids in [None,['unknown'],[IDS[0],IDS[0]],[IDS[1]],IDS[::-1]]:
            assert request(base,ctx,'POST','/migrations',ids)[0]==400
            assert sql(db,"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name='samples'",(db,))[0][0]==0
        # Simulate completed DDL followed by interruption before its history write.
        sql(db,'CREATE TABLE samples (id VARCHAR(80) PRIMARY KEY,name VARCHAR(160) NOT NULL)')
        sql(db,'INSERT INTO samples(id,name) VALUES (%s,%s)',('resume-row','Synthetic retained row'))
        expect(request(base,ctx,'POST','/migrations',IDS[:1]),200,{'applied':IDS[:1],'all':IDS[:1]})
        assert sql(db,'SELECT name FROM samples WHERE id=%s',('resume-row',))[0][0]=='Synthetic retained row'
        sql(db,'INSERT INTO samples(id,name) VALUES (%s,%s)',('synthetic-record','Synthetic sample'))
        expect(request(base,ctx,'POST','/migrations',IDS),200,{'applied':IDS[1:],'all':IDS})
        assert sql(db,'SELECT category FROM samples WHERE id=%s',('synthetic-record',))[0][0]=='general'
        assert sql(db,"SHOW INDEX FROM samples WHERE Key_name='sample_category'")
    with server(binary,db,certdir,password) as (base,ctx):
        expect(request(base,ctx,'POST','/migrations',IDS),200,{'applied':[],'all':IDS})
        assert request(base,ctx,'GET','/health')[1]['migration_count']==3
        assert [r[0] for r in sql(db,'SELECT migration_id FROM schema_migrations ORDER BY sequence_id')]==IDS
        before=sql(db,'SELECT migration_id FROM schema_migrations ORDER BY sequence_id')
        expect(request(base,ctx,'POST','/migrations',IDS[::-1]),400,{'error':'invalid_migrations'})
        assert sql(db,'SELECT migration_id FROM schema_migrations ORDER BY sequence_id')==before

def ru004(binary,db,certdir,password):
    with server(binary,db,certdir,password) as (base,ctx):
        expect(request(base,ctx,'GET','/secure'),403,{'error':'certificate_required'})
        assert request(base,ctx,'GET','/secure',headers={'X-Client-Certificate':'synthetic flag'})[0]==403
        expect(request(base,context(certdir,'client'),'GET','/secure'),200,{'message':'certificate accepted','migration_count':0})
        try:status,body=request(base,context(certdir,'untrusted'),'GET','/secure')
        except (OSError,urllib.error.URLError,ssl.SSLError):pass
        else:assert status>=400

def ru005(binary,db,certdir,password):
    with server(binary,db,certdir,password) as (base,ctx):
        expect(request(base,ctx,'GET','/samples'),503,{'error':'api_not_ready'})
        expect(request(base,ctx,'GET','/missing'),404,{'error':'unknown_endpoint'})
        seed_schema(db)
        for ident in ['z','a']:sql(db,'INSERT INTO samples(id,name,category) VALUES (%s,%s,%s)',(ident,'Synthetic '+ident,'example'))
        status,rows=request(base,ctx,'GET','/samples');assert status==200 and len(rows)==2
        for row,ident in zip(rows,['a','z']):subset(row,{'id':ident,'name':'Synthetic '+ident,'category':'example'})
        expect(request(base,ctx,'GET','/health'),200,{'database_connected':True,'migration_count':3,'tls_configured':True})

def main():
    global ACTIVE
    if os.geteuid()!=0 or not DOTNET:return {'harness_ok':False,'error':'Prepared evaluator identity/SDK unavailable','results':[]}
    # Candidate cannot mutate or read the evaluator, its DB admin password, or client certificate keys.
    script="import shutil,sys,tempfile,os;from pathlib import Path;p=Path(tempfile.mkdtemp(prefix='candidate-build-'));p.chmod(0o755);shutil.copytree(sys.argv[1],p/'src',ignore=shutil.ignore_patterns('runtime','.git','bin','obj','.build','.dotnet-home'));print(p)"
    copied=subprocess.run([sys.executable,'-I','-c',script,str(ROOT)],capture_output=True,text=True,user=1000,group=1000,extra_groups=[])
    if copied.returncode:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':'Candidate source unavailable'} for i in range(1,6)]}
    work=Path(copied.stdout.strip());src=work/'src';binary=src/'.build/SetupApi.dll'
    rows=[]
    try:
        for args in [[DOTNET,'restore',str(src/'SetupApi.csproj'),'--configfile','/opt/sweclar/NuGet.Config'],[DOTNET,'build',str(src/'SetupApi.csproj'),'--no-restore','-p:UseSharedCompilation=false','-o',str(binary.parent)]]:
            build=subprocess.run(args,cwd=src,env={**CANDIDATE_ENV,'HOME':str(work),'DOTNET_CLI_HOME':str(work)},text=True,capture_output=True,timeout=40,user=1000,group=1000,extra_groups=[])
            if build.returncode:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':'Candidate build failed'} for i in range(1,6)]}
        with tempfile.TemporaryDirectory(prefix='private-tls-') as temp:
            certdir=Path(temp);password=certificates(certdir)
            for index,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
                with DatabaseFixture() as fixture:
                    ACTIVE=fixture
                    try:test(binary,fixture.database,certdir,password);row={'ru_id':f'RU-{index:03}','passed':True}
                    except (TimeoutError,subprocess.TimeoutExpired):raise
                    except Exception as error:row={'ru_id':f'RU-{index:03}','passed':False,'detail':str(error) or type(error).__name__}
                    rows.append(row)
        return {'harness_ok':True,'results':rows}
    finally:
        subprocess.run([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(work)],user=1000,group=1000,extra_groups=[],check=True)

if __name__=='__main__':
    try:result=main()
    except Exception as error:result={'harness_ok':False,'error':str(error),'results':[]}
    print(json.dumps(result))
