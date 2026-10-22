"""Protected process and virtual-I/O support; task grading decisions stay outside."""
import json
import os
import select
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class CandidateFailure(AssertionError):pass


def identity():return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}


class Board:
    def __init__(self):
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.socket.bind(('127.0.0.1',0));self.socket.setblocking(False);self.port=self.socket.getsockname()[1]
    def drain(self):
        result=[]
        while True:
            try:result.append(self.socket.recv(1024))
            except BlockingIOError:return result
    def __enter__(self):return self
    def __exit__(self,*_):self.socket.close()


class Bus:
    def __init__(self,auto_ack=True,ack=b'OK01'):
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen();self.listener.settimeout(0.1)
        self.port=self.listener.getsockname()[1];self.ack=ack;self.hellos=[];self.records=[];self.clients=[];self.threads=[];self.stop=threading.Event();self.release=threading.Event()
        if auto_ack:self.release.set()
        self.thread=threading.Thread(target=self.accept,daemon=True)
    def accept(self):
        while not self.stop.is_set():
            try:client,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:return
            self.clients.append(client);worker=threading.Thread(target=self.handle,args=(client,),daemon=True);self.threads.append(worker);worker.start()
    def handle(self,client):
        def exact(n):
            data=b''
            while len(data)<n:
                part=client.recv(n-len(data))
                if not part:return None
                data+=part
            return data
        try:
            hello=exact(4);self.hellos.append(hello)
            self.release.wait()
            if self.stop.is_set():return
            client.sendall(self.ack[:2]);time.sleep(0.003);client.sendall(self.ack[2:])
            while not self.stop.is_set():
                record=exact(12)
                if record is None:return
                self.records.append(record)
        except OSError:return
        finally:client.close()
    def disconnect(self):
        for client in list(self.clients):
            try:client.shutdown(socket.SHUT_RDWR);client.close()
            except OSError:pass
    def wait_records(self,count):
        deadline=time.monotonic()+2
        while len(self.records)<count and time.monotonic()<deadline:time.sleep(0.005)
        if len(self.records)<count:raise CandidateFailure(f'Expected {count} actual bus frames, got {len(self.records)}')
        return list(self.records)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*_):
        self.stop.set();self.release.set();self.disconnect();self.listener.close();self.thread.join(timeout=1)
        for worker in self.threads:worker.join(timeout=1)


class Firmware:
    def __init__(self,project,board,bus):
        self.project=Path(project);self.board=board;self.bus=bus;self.process=None;self.pending=b'';self.temp=tempfile.TemporaryDirectory(prefix='sweclar-firmware-');self.log=None
        os.chmod(self.temp.name,0o777)
    def start(self):
        build=subprocess.Popen(['make'],cwd=self.project,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':self.temp.name},**identity())
        try:output=build.communicate(timeout=30)[0]
        except subprocess.TimeoutExpired:
            os.killpg(build.pid,signal.SIGKILL);build.communicate();raise CandidateFailure('Candidate build exceeded 30s after toolchain preflight')
        if build.returncode:raise CandidateFailure('Candidate build failed: '+output.decode(errors='replace')[-3000:])
        self.log=open(Path(self.temp.name)/'stderr.log','w+')
        try:
            self.process=subprocess.Popen([str(self.project/'build/firmware'),'--board-port',str(self.board.port),'--bus-port',str(self.bus.port)],cwd=self.project,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':self.temp.name},**identity())
        except OSError as error:raise CandidateFailure('Candidate executable unavailable: '+str(error)) from error
        self.startup=self.read_line();self.registration_port=int(self.startup['registration_port']);return self
    def read_line(self,timeout=2):
        deadline=time.monotonic()+timeout
        while b'\n' not in self.pending:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([self.process.stdout],[],[],remaining)[0]:raise CandidateFailure('Candidate command/startup did not respond within 2s')
            data=os.read(self.process.stdout.fileno(),65536)
            if not data:raise CandidateFailure('Candidate exited without a command response')
            self.pending+=data
        line,self.pending=self.pending.split(b'\n',1)
        try:return json.loads(line)
        except (ValueError,UnicodeError) as error:raise CandidateFailure('Candidate returned invalid JSON') from error
    def command(self,text,ok=True):
        try:self.process.stdin.write(text.encode()+b'\n');self.process.stdin.flush()
        except (OSError,ValueError) as error:raise CandidateFailure('Candidate command input failed') from error
        result=self.read_line()
        if result.get('ok') is not ok:raise CandidateFailure(f'{text}: expected ok={ok}, got {result}')
        return result
    def wait_status(self,**expected):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            state=self.command('status')
            if all(state.get(k)==v for k,v in expected.items()):return state
            time.sleep(0.005)
        raise CandidateFailure('Candidate connection status did not reach '+str(expected))
    def stop(self):
        if self.process:
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
            self.process.stdin.close();self.process.stdout.close();self.process=None
        if self.log:self.log.close();self.log=None
    def __enter__(self):
        try:return self.start()
        except BaseException:self.__exit__(None,None,None);raise
    def __exit__(self,*_):self.stop();self.temp.cleanup()
