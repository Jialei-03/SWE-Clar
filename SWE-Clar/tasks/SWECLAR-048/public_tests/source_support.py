"""Independent synthetic source fixture; contains no application-policy answers."""
import json
import secrets
import socket
import struct
import threading
import time


def exact(stream,count):
    data=b''
    while len(data)<count:
        part=stream.recv(count-len(data))
        if not part:raise EOFError()
        data+=part
    return data


class Source:
    def __init__(self):
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen();self.listener.settimeout(0.1)
        self.port=self.listener.getsockname()[1];self.stop=threading.Event();self.clients=[];self.workers=[];self.requests=[];self.lock=threading.Lock()
        self.devices=[{'id':'SOURCE-A','name':'Synthetic source A','preferred':False},{'id':'SOURCE-B','name':'Synthetic source B','preferred':False}]
        self.width=31;self.height=19;self.seed=secrets.randbelow(100);self.sequence=0;self.frozen=11;self.fragment=True
        self.thread=threading.Thread(target=self.accept,daemon=True)
    def rgb_at(self,x,y,sequence,input_='preview',device='SOURCE-A'):
        offset=113 if input_=='auxiliary' else (71 if device=='SOURCE-B' else 0)
        return [(x*5+self.seed+sequence+offset)%256,(y*7+offset)%256,(x+y*3+sequence*11)%256]
    def response(self,request):
        if request=={'op':'list'}:
            body=json.dumps(self.devices).encode();return b'LST1'+struct.pack('!I',len(body))+body
        assert request['op']=='frame' and request['input'] in ('preview','auxiliary')
        if request['input']=='preview':assert request.get('device_id') in [x['id'] for x in self.devices]
        with self.lock:self.sequence+=1;sequence=self.sequence if self.frozen is None else self.frozen
        rgb=bytes(v for y in range(self.height) for x in range(self.width) for v in self.rgb_at(x,y,sequence,request['input'],request.get('device_id')))
        return b'FRM1'+struct.pack('!IHHI',sequence,self.width,self.height,len(rgb))+rgb
    def accept(self):
        while not self.stop.is_set():
            try:client,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:return
            self.clients.append(client);worker=threading.Thread(target=self.handle,args=(client,),daemon=True);self.workers.append(worker);worker.start()
    def handle(self,client):
        try:
            client.settimeout(3);size=struct.unpack('!I',exact(client,4))[0];assert 2<=size<=4096
            request=json.loads(exact(client,size));self.requests.append(request)
            payload=self.response(request)
            if self.fragment:
                client.sendall(payload[:1]);time.sleep(0.002);client.sendall(payload[1:5]);time.sleep(0.002);client.sendall(payload[5:])
            else:client.sendall(payload)
        except (OSError,EOFError,ValueError,AssertionError,KeyError,TypeError):pass
        finally:client.close()
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*_):
        self.stop.set();self.listener.close()
        for client in self.clients:
            try:client.shutdown(socket.SHUT_RDWR);client.close()
            except OSError:pass
        self.thread.join(timeout=2)
        for worker in self.workers:worker.join(timeout=2)
