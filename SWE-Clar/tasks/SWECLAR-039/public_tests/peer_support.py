"""Independent benchmark-owned framed TCP peer, started before the application."""
import json
import socketserver
import struct
import threading
import time


def frame(value):
    data=json.dumps(value,ensure_ascii=False).encode()
    return struct.pack('!I',len(data))+data


def read_exact(stream,n):
    chunks=[]
    while n:
        data=stream.recv(n)
        if not data: raise ValueError('Truncated candidate request')
        chunks.append(data);n-=len(data)
    return b''.join(chunks)


class Peer:
    def __init__(self):
        self.requests=[];self.fragment=True
        self.devices=[{'device_id':'PUBLIC-A','name':'Public <sensor> A','services':['capture.v1']},
                      {'device_id':'OTHER','name':'Other','services':['other.v1']},
                      {'device_id':'PUBLIC-A','name':'Updated <sensor> A','services':['capture.v1']}]
        owner=self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    size=struct.unpack('!I',read_exact(self.request,4))[0]
                    if not 1<=size<=65536: return
                    request=json.loads(read_exact(self.request,size))
                    with owner.lock:
                        owner.requests.append(request)
                        response=owner.respond(request)
                    data=response if isinstance(response,bytes) else b''.join(frame(value) for value in response)
                    if owner.fragment:
                        # Split the header and body, then coalesce any following frames.
                        for begin,end in [(0,1),(1,3),(3,7),(7,len(data))]:
                            self.request.sendall(data[begin:end])
                            time.sleep(0.003)
                    else:self.request.sendall(data)
                except (OSError,ValueError,KeyError,TypeError):return
        self.server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.port=self.server.server_address[1];self.lock=threading.Lock()
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True)
    def respond(self,request):
        return [{'ok':True,'devices':self.devices}] if request.get('op')=='scan' else [{'ok':False}]
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*_):self.server.shutdown();self.server.server_close();self.thread.join()
