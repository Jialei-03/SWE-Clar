"""Public stateless MQTT 3.1.1 QoS0 development fixture on loopback:1883.
Each subscription to synthetic/sensor receives the documented fixed example.
"""
import json,socket,socketserver

def packet(kind,body):
    size=len(body);header=bytearray([kind])
    while True:
        digit=size%128;size//=128;header.append(digit|(128 if size else 0))
        if not size:return bytes(header)+body

def string(value):
    raw=value.encode();return len(raw).to_bytes(2,'big')+raw

class Connection(socketserver.BaseRequestHandler):
    def handle(self):
        sock=self.request;sock.settimeout(15)
        def exact(size):
            out=b''
            while len(out)<size:
                part=sock.recv(size-len(out))
                if not part:raise EOFError()
                out+=part
            return out
        try:
            while True:
                header=exact(1)[0];size=0;factor=1
                for _ in range(4):
                    digit=exact(1)[0];size+=(digit&127)*factor;factor*=128
                    if digit<128:break
                else:return
                body=exact(size)
                if header==16:
                    if body[:7]!=b'\x00\x04MQTT\x04':return
                    sock.sendall(b'\x20\x02\0\0')
                elif header==130:
                    mid=body[:2];i=2;topics=[];codes=[]
                    while i<len(body):
                        n=int.from_bytes(body[i:i+2],'big');topics.append(body[i+2:i+2+n].decode());codes.append(0 if body[i+2+n]==0 else 128);i+=n+3
                    sock.sendall(packet(144,mid+bytes(codes)))
                    for topic,code in zip(topics,codes):
                        if topic=='synthetic/sensor' and code==0:
                            sock.sendall(packet(48,string(topic)+json.dumps({'timestamp':1,'values':{'value':20}}).encode()))
                elif header==192:sock.sendall(b'\xd0\0')
                elif header==224:return
                else:return
        except (OSError,EOFError,ValueError,IndexError):return

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True

if __name__=='__main__':
    with Server(('127.0.0.1',1883),Connection) as server:server.serve_forever()
