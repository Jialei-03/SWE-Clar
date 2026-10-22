"""Independent native toolchain, loopback and process-identity preflight."""
import json
import os
import subprocess
import tempfile
from pathlib import Path


def preflight():
    with tempfile.TemporaryDirectory(prefix='sweclar-native-health-') as directory:
        path=Path(directory);os.chmod(path,0o777)
        source=path/'probe.cpp'
        source.write_text('''#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <iostream>
int main(){
 if(getuid()!=1000) return 1;
 int fd=socket(AF_INET,SOCK_DGRAM,0);sockaddr_in a{};a.sin_family=AF_INET;a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
 if(bind(fd,reinterpret_cast<sockaddr*>(&a),sizeof(a)))return 2;
 socklen_t n=sizeof(a);getsockname(fd,reinterpret_cast<sockaddr*>(&a),&n);
 if(sendto(fd,"probe",5,0,reinterpret_cast<sockaddr*>(&a),n)!=5)return 3;
 pollfd p{fd,POLLIN,0};if(poll(&p,1,1000)!=1)return 4;
 char b[5];if(recv(fd,b,5,0)!=5)return 5;
 close(fd);std::cout<<"native-loopback-ok";return 0;
}
''')
        identity={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
        subprocess.run(['g++','-std=c++17',str(source),'-o',str(path/'probe')],check=True,capture_output=True,timeout=30,**identity)
        checked=subprocess.run([str(path/'probe')],check=True,capture_output=True,text=True,timeout=5,**identity)
        assert checked.stdout=='native-loopback-ok'
        denied=subprocess.run(['sh','-c','test ! -r /private && test ! -w /opt/sweclar/preflight.py'],**identity)
        assert denied.returncode==0
    compiler=subprocess.check_output(['g++','-dumpfullversion'],text=True).strip()
    assert compiler=='14.2.0',compiler
    return {'passed':True,'compiler':'g++ '+compiler,'python':subprocess.check_output(['python3','--version'],text=True).strip(),'architecture':os.uname().machine,'native_execution':True,'loopback':True,'candidate_uid':1000}


if __name__=='__main__':print(json.dumps(preflight()))
