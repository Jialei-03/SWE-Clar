"""Standalone, synthetic raw-video source for local development."""
import json
import socketserver
import struct
import threading
from wire import exact


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(2)
            size=struct.unpack('!I',exact(self.request,4))[0]
            if not 2<=size<=4096:return
            request=json.loads(exact(self.request,size))
            if request.get('op')=='list':
                devices=[{'id':'CAM-A','name':'Pattern camera','preferred':False},{'id':'CAM-B','name':'Moving bars','preferred':True}]
                data=json.dumps(devices).encode();self.request.sendall(b'LST1'+struct.pack('!I',len(data))+data);return
            if request.get('op')!='frame':return
            if request.get('input')=='preview' and request.get('device_id') not in ('CAM-A','CAM-B'):return
            with self.server.lock:self.server.sequence+=1;sequence=self.server.sequence
            width,height=96,72
            mode=2 if request.get('input')=='auxiliary' else (1 if request.get('device_id')=='CAM-B' else 0)
            rgb=bytearray()
            for y in range(height):
                for x in range(width):
                    rgb.extend(((x*3+sequence*5+mode*67)%256,(y*4+mode*83)%256,((x+y)*2+sequence*3)%256))
            self.request.sendall(b'FRM1'+struct.pack('!IHHI',sequence,width,height,len(rgb))+rgb)
        except (OSError,ValueError,KeyError,TypeError):return


class Source(socketserver.ThreadingTCPServer):
    daemon_threads=True
    def __init__(self):
        super().__init__(('127.0.0.1',0),Handler);self.sequence=0;self.lock=threading.Lock()
    def start(self):
        self.thread=threading.Thread(target=self.serve_forever,daemon=True);self.thread.start();return self.server_address[1]
    def stop(self):self.shutdown();self.server_close();self.thread.join(timeout=2)
