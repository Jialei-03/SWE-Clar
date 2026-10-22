"""Task-local Linux diagnostic; no changes to shared process/runtime sources."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
from harness import Firmware,identity,CandidateFailure

class FaultUnavailable(RuntimeError):pass

class ShortWriteFirmware(Firmware):
    def start(self):
        source=Path(__file__).with_name('short_writes.c')
        self.fault_temp=tempfile.TemporaryDirectory(prefix='sweclar-short-write-')
        Path(self.fault_temp.name).chmod(0o755)
        self.library=Path(self.fault_temp.name)/'short-writes.so'
        self.mode=Path(self.fault_temp.name)/'fault-mode'
        self.mode.write_text('S');self.mode.chmod(0o644)
        try:built=subprocess.run(['gcc','-shared','-fPIC','-O2',str(source),'-ldl','-o',str(self.library)],capture_output=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired) as error:raise FaultUnavailable('Short-write compiler unavailable: '+str(error)) from error
        if built.returncode:raise FaultUnavailable('Short-write fixture compilation failed: '+built.stderr.decode()[-1000:])
        self.library.chmod(0o755)
        try:build=subprocess.run(['make'],cwd=self.project,capture_output=True,timeout=30,env={'PATH':os.environ['PATH'],'HOME':self.temp.name},**identity())
        except subprocess.TimeoutExpired as error:raise CandidateFailure('Candidate build exceeded 30s') from error
        if build.returncode:raise CandidateFailure('Candidate build failed: '+build.stderr.decode()[-1000:])
        self.log=open(Path(self.temp.name)/'stderr.log','w+')
        self.process=subprocess.Popen([str(self.project/'build/firmware'),'--board-port',str(self.board.port),'--bus-port',str(self.bus.port)],cwd=self.project,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,start_new_session=True,env={'PATH':os.environ['PATH'],'HOME':self.temp.name,'LD_PRELOAD':str(self.library),'CLARSWE_FAULT_BUS_PORT':str(self.bus.port),'CLARSWE_FAULT_MODE':str(self.mode)},**identity())
        self.startup=self.read_line();self.registration_port=int(self.startup['registration_port']);return self
    def __exit__(self,*args):
        try:super().__exit__(*args)
        finally:
            if hasattr(self,'fault_temp'):self.fault_temp.cleanup()
    def fault_log(self):return (Path(self.temp.name)/'stderr.log').read_text(errors='replace')
    def require_fault(self,name,after=0):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if 'CLARSWE_FAULT_'+name in self.fault_log()[after:]:return
            time.sleep(.005)
        # Static/direct-syscall implementations need a kernel-level injector.
        # An unexercised diagnostic is infrastructure-unqualified, not a failure
        # of a permitted implementation strategy.
        raise FaultUnavailable('Cannot exercise '+name+' through libc; kernel-level injection qualification required')
