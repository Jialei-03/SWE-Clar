"""Exercise supplied adapters without requiring unfinished business transitions."""
import base64,json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path

def main():
    project=Path(os.environ.get('CANDIDATE_ROOT',os.getcwd()))
    with tempfile.TemporaryDirectory() as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        def request(path,body=None):
            content=None if body is None else json.dumps(body).encode()
            with urllib.request.urlopen(urllib.request.Request(base+path,data=content,headers={'Content-Type':'application/json'}),timeout=3) as response:
                return response.read()
        def start():
            p=subprocess.Popen([sys.executable,str(project/'server.py'),'--port',str(port),'--data',data],cwd=project,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            for _ in range(100):
                try:request('/api/order');return p
                except (OSError,TimeoutError):
                    if p.poll() is not None:raise AssertionError(p.stderr.read().decode())
                    time.sleep(.05)
            p.terminate();p.wait();raise AssertionError('Local adapter did not start')
        p=start()
        try:
            order=json.loads(request('/api/order'));assert order['status']=='created'
            assert b'<form' in request('/')
            blob=b'synthetic proof bytes\x00\xff'
            ref=json.loads(request('/api/proofs',{'data':base64.b64encode(blob).decode()}))['ref']
            assert request(ref)==blob
        finally:p.terminate();p.wait(timeout=5)
        p=start()
        try:
            assert request(ref)==blob
            assert json.loads(request('/api/order'))==order
        finally:p.terminate();p.wait(timeout=5)
    print('Public adapter checks passed: HTTP, persistent order read and exact proof-byte round trip.')

if __name__=='__main__':main()
