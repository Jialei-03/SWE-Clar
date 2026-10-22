"""Protected parent drives unprivileged app and browser with fresh storage."""
import base64,json,os,socket,subprocess,sys,time,urllib.request,uuid
from pathlib import Path

class InfrastructureError(Exception):pass

def run():
    root=Path(os.environ['CANDIDATE_ROOT']);data='/tmp/delivery-'+uuid.uuid4().hex
    env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','PLAYWRIGHT_BROWSERS_PATH':'/ms-playwright'}
    def worker(args,**kw):return subprocess.run(args,cwd=root,user=1000,group=1000,extra_groups=[],env=env,capture_output=True,text=True,timeout=30,**kw)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}/'
    def request(path,body=None):
        with urllib.request.urlopen(urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=3) as r:return r.read()
    def start():
        p=subprocess.Popen([sys.executable,str(root/'server.py'),'--port',str(port),'--data',data],cwd=root,user=1000,group=1000,extra_groups=[],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:request('api/order');return p
            except OSError:
                if p.poll() is not None:raise AssertionError('Candidate HTTP server stopped')
                time.sleep(.05)
        p.terminate();p.wait();raise AssertionError('Candidate HTTP server did not start')
    p=None
    try:
        p=start()
        blob=b'independent synthetic bytes\x00\xff'
        ref=json.loads(request('api/proofs',{'data':base64.b64encode(blob).decode()}))['ref']
        assert request(ref.lstrip('/'))==blob
        result=worker([sys.executable,'-I','/public_tests/browser_observe.py'],input=json.dumps({'url':base,'steps':[{'type':'assign'},{'type':'pickup'},{'type':'deliver','receiver':'Synthetic receiver','upload':True}]}))
        if result.returncode==2 and 'infrastructure_error' in result.stdout:raise InfrastructureError(result.stdout)
        assert result.returncode==0,result.stderr[-1000:]
        observed=json.loads(result.stdout);order=observed['order']
        assert order['status']=='delivered' and order['proof']['receiver']=='Synthetic receiver'
        assert request(order['proof']['photo'].lstrip('/'))==b'synthetic proof file'
        assert 'delivered' in observed['text'],'UI did not render persisted state'
        p.terminate();p.wait(timeout=5);p=None;p=start()
        assert json.loads(request('api/order'))==order and request(ref.lstrip('/'))==blob
        invalid=json.loads(request('api/event',{'type':'assign'}));assert invalid.get('error')
        assert json.loads(request('api/order'))==order,'Rejected event persisted'
    finally:
        if p is not None:p.terminate();p.wait(timeout=5)
        worker([sys.executable,'-c','import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)',data])
