"""Newline-delimited JSON communication with the prepared local driver."""
import json
import math
import socket


def send(port, sequence, points, positions):
    request = {'sequence': sequence, 'points': points, 'positions': positions}
    with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
        connection.sendall((json.dumps(request, allow_nan=False) + '\n').encode())
        with connection.makefile('rb') as stream:
            line = stream.readline(65537)
    if not line.endswith(b'\n') or len(line) > 65536:
        raise ValueError('Incomplete driver response')
    response = json.loads(line)
    # Finish acknowledgement and result-shape validation.
    return response
