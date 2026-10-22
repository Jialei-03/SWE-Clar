"""Length-prefixed UTF-8 JSON framing for a prepared loopback peer."""
import json
import socket
import struct


def exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.recv(size - len(result))
        if not chunk:
            raise ValueError('Truncated peer frame')
        result.extend(chunk)
    return bytes(result)


def receive(stream):
    size = struct.unpack('!I', exact(stream, 4))[0]
    if not 1 <= size <= 65536:
        raise ValueError('Peer frame length outside 1..65536')
    def reject_constant(value):
        raise ValueError('Nonfinite JSON number')
    value = json.loads(exact(stream, size).decode('utf-8'), parse_constant=reject_constant)
    json.dumps(value, allow_nan=False)
    return value


def transmit(stream, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if not 1 <= len(data) <= 65536:
        raise ValueError('Request frame length outside 1..65536')
    stream.sendall(struct.pack('!I', len(data)) + data)


def exchange(port, request):
    with socket.create_connection(('127.0.0.1', port), timeout=2) as stream:
        transmit(stream, request)
        response = receive(stream)
        if not isinstance(response, dict) or type(response.get('ok')) is not bool:
            raise ValueError('Peer response requires boolean ok')
        packets = []
        if request['op'] == 'command' and response['ok']:
            count = response.get('packet_count')
            if type(count) is not int or not 0 <= count <= 64:
                raise ValueError('Invalid packet count')
            packets = [receive(stream) for _ in range(count)]
        return response, packets
