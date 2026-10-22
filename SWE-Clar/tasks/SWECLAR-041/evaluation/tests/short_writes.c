/* Linux diagnostic: preserve socket semantics while forcing legal short writes.
 * Only the prepared bus peer is affected; serial/UDP/registration are untouched.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>

static ssize_t (*real_write)(int,const void*,size_t);
static int marked_block;
static char last_mode;
static size_t blocked_bytes;
static int is_bus(int fd) {
    struct sockaddr_in peer; socklen_t size=sizeof(peer);
    const char *port=getenv("CLARSWE_FAULT_BUS_PORT");
    return port && !getpeername(fd,(struct sockaddr*)&peer,&size)
        && peer.sin_family==AF_INET && ntohs(peer.sin_port)==atoi(port);
}
static void mark(const char *text) {
    if (!real_write) real_write=dlsym(RTLD_NEXT,"write");
    real_write(2,text,strlen(text));
}
static size_t limit(int fd,size_t count) {
    struct sockaddr_in peer; socklen_t size=sizeof(peer);
    const char *port=getenv("CLARSWE_FAULT_BUS_PORT"), *path=getenv("CLARSWE_FAULT_MODE");
    if (!count || !port || !path || getpeername(fd,(struct sockaddr*)&peer,&size)
        || peer.sin_family!=AF_INET || ntohs(peer.sin_port)!=atoi(port)) return count;
    char mode='S';int control=open(path,O_RDONLY);
    if(control>=0){if(read(control,&mode,1)!=1)mode='S';close(control);}
    if(mode!=last_mode){blocked_bytes=0;last_mode=mode;}
    if(mode=='B' && blocked_bytes>=3){
        if(!marked_block){mark("CLARSWE_FAULT_BLOCK\n");marked_block=1;}
        errno=EAGAIN;return 0;
    }
    size_t n=count>3?3:count;
    if(mode=='B' && n>3-blocked_bytes)n=3-blocked_bytes;
    if(n<count)mark("CLARSWE_FAULT_SHORT\n");
    return n;
}
static ssize_t counted(int fd,ssize_t n){if(n>0 && last_mode=='B' && is_bus(fd))blocked_bytes+=(size_t)n;return n;}
ssize_t write(int fd,const void *buf,size_t count) {
    if(!real_write)real_write=dlsym(RTLD_NEXT,"write");
    size_t n=limit(fd,count);if(count&&!n)return -1;
    return counted(fd,real_write(fd,buf,n));
}
ssize_t send(int fd,const void *buf,size_t count,int flags) {
    ssize_t (*fn)(int,const void*,size_t,int)=dlsym(RTLD_NEXT,"send");
    size_t n=limit(fd,count);if(count&&!n)return -1;
    return counted(fd,fn(fd,buf,n,flags));
}
ssize_t sendto(int fd,const void *buf,size_t count,int flags,const struct sockaddr *addr,socklen_t len) {
    ssize_t (*fn)(int,const void*,size_t,int,const struct sockaddr*,socklen_t)=dlsym(RTLD_NEXT,"sendto");
    size_t n=limit(fd,count);if(count&&!n)return -1;
    return counted(fd,fn(fd,buf,n,flags,addr,len));
}
ssize_t sendmsg(int fd,const struct msghdr *msg,int flags) {
    ssize_t (*fn)(int,const struct msghdr*,int)=dlsym(RTLD_NEXT,"sendmsg");
    size_t total=0;for(size_t i=0;i<msg->msg_iovlen;i++)total+=msg->msg_iov[i].iov_len;
    size_t n=limit(fd,total);if(total&&!n)return -1;
    if(n==total)return counted(fd,fn(fd,msg,flags));
    struct iovec parts[msg->msg_iovlen];size_t left=n,used=0;
    for(size_t i=0;i<msg->msg_iovlen&&left;i++){parts[used]=msg->msg_iov[i];if(parts[used].iov_len>left)parts[used].iov_len=left;left-=parts[used++].iov_len;}
    struct msghdr copy=*msg;copy.msg_iov=parts;copy.msg_iovlen=used;
    return counted(fd,fn(fd,&copy,flags));
}
ssize_t writev(int fd,const struct iovec *iov,int count) {
    ssize_t (*fn)(int,const struct iovec*,int)=dlsym(RTLD_NEXT,"writev");
    if(count<=0)return fn(fd,iov,count);
    size_t total=0;for(int i=0;i<count;i++)total+=iov[i].iov_len;
    size_t n=limit(fd,total);if(total&&!n)return -1;
    if(n==total)return counted(fd,fn(fd,iov,count));
    struct iovec parts[count];size_t left=n;int used=0;
    for(int i=0;i<count&&left;i++){parts[used]=iov[i];if(parts[used].iov_len>left)parts[used].iov_len=left;left-=parts[used++].iov_len;}
    return counted(fd,fn(fd,parts,used));
}
