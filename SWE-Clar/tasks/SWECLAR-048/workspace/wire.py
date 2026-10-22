import json
import re
import socket
import struct


class SourceError(ValueError):pass


def exact(stream, count):
    result=bytearray()
    while len(result)<count:
        part=stream.recv(count-len(result))
        if not part:raise SourceError('truncated_source')
        result.extend(part)
    return bytes(result)


def exchange(port, command):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1.5) as stream:
            payload=json.dumps(command,separators=(',',':')).encode()
            stream.sendall(struct.pack('!I',len(payload))+payload)
            magic=exact(stream,4)
            if command['op']=='list':
                if magic!=b'LST1':raise SourceError('invalid_catalog')
                size=struct.unpack('!I',exact(stream,4))[0]
                if not 2<=size<=65536:raise SourceError('invalid_catalog')
                devices=json.loads(exact(stream,size))
                if not isinstance(devices,list) or len(devices)>32:raise SourceError('invalid_catalog')
                seen=set()
                for item in devices:
                    if not isinstance(item,dict) or set(item)!={'id','name','preferred'}:raise SourceError('invalid_catalog')
                    if not isinstance(item['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',item['id']) or item['id'] in seen:raise SourceError('invalid_catalog')
                    if not isinstance(item['name'],str) or not 1<=len(item['name'])<=80 or type(item['preferred']) is not bool:raise SourceError('invalid_catalog')
                    seen.add(item['id'])
                return devices
            if magic!=b'FRM1':raise SourceError('invalid_frame')
            sequence,width,height,size=struct.unpack('!IHHI',exact(stream,12))
            if not 8<=width<=320 or not 8<=height<=240 or size!=width*height*3:raise SourceError('invalid_frame')
            return sequence,width,height,exact(stream,size)
    except (OSError,ValueError,UnicodeError) as error:
        if isinstance(error,SourceError):raise
        raise SourceError('source_unavailable') from error
