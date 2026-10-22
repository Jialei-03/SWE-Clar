"""Local demo Firestore service: public operations, no task answers or assertions."""
import contextlib,json,os,pathlib,socket,subprocess,tempfile,time,urllib.request,urllib.error
PROJECT='demo-sweclar'
DOCUMENTS='/v1/projects/'+PROJECT+'/databases/(default)/documents'
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(origin,method,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(origin+path,data=data,method=method,headers={'Content-Type':'application/json'})
    try:
        with OPENER.open(req,timeout=15) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:
        return error.code,json.load(error)


def start(root,port=0):
    root=pathlib.Path(root);root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o755)
    home=root/'home';home.mkdir(exist_ok=True)
    if os.geteuid()==0:os.chown(home,1000,1000)
    if not port:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    log=(root/'firestore.log').open('w')
    options={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
    command=['/opt/jre/bin/java','-Xms32m','-Xmx384m','-XX:ActiveProcessorCount=2','-Djava.io.tmpdir='+str(home),'-jar','/opt/firestore/emulator.jar','--host','127.0.0.1','--port',str(port),'--project_id',PROJECT,'--single_project_mode','true']
    process=subprocess.Popen(command,cwd=home,env={'PATH':os.environ['PATH'],'HOME':str(home)},stdout=log,stderr=log,start_new_session=True,**options)
    origin='http://127.0.0.1:'+str(port)
    try:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Prepared Firestore process exited; see '+str(root/'firestore.log'))
            try:
                if request(origin,'GET',DOCUMENTS+'/health')[0]==200:return process,origin,log
            except (OSError,ValueError):pass
            time.sleep(.15)
        raise RuntimeError('Prepared Firestore startup timed out')
    except BaseException:
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        log.close();raise


def stop(process,log):
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    log.close()


@contextlib.contextmanager
def session(root):
    process,origin,log=start(root)
    try:yield origin
    finally:stop(process,log)


def seed(origin,documents):
    for path,fields in documents.items():
        status,_=request(origin,'PATCH',DOCUMENTS+'/'+path,{'fields':fields})
        if status!=200:raise RuntimeError('Prepared demo seed failed: '+str(status))
