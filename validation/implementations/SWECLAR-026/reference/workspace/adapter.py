"""Newline-delimited JSON communication with the prepared local driver."""
import json
import socket

from geometry import valid_number


_MAX_LINE = 65536


def _protocol_error(message='Invalid driver response'):
    raise ValueError(message)


def _validate_response(response, sequence, positions):
    if not isinstance(response, dict):
        _protocol_error('Driver response must be a JSON object')

    response_sequence = response.get('sequence')
    if type(response_sequence) is not int or response_sequence != sequence:
        _protocol_error('Driver acknowledgement did not match the request')

    receipt = response.get('receipt')
    if not isinstance(receipt, str):
        _protocol_error('Driver receipt must be a string')

    samples = response.get('samples')
    if not isinstance(samples, list) or len(samples) != len(positions):
        _protocol_error('Driver returned the wrong number of samples')

    checked_samples = []
    for expected_x, sample in zip(positions, samples):
        if not isinstance(sample, dict):
            _protocol_error('Driver samples must be objects')
        sample_x = sample.get('x')
        sample_y = sample.get('y')
        # Check the X type as well as equality: False == 0 and True == 1 in
        # Python, but booleans are not coordinate values.
        if type(sample_x) not in (int, float) or sample_x != expected_x:
            _protocol_error('Driver returned an unexpected sample position')
        if not valid_number(sample_y):
            _protocol_error('Driver returned an invalid sample value')
        # Normalize the public shape and discard any driver-specific response
        # fields.  The values themselves remain the driver's values.
        checked_samples.append({'x': sample_x, 'y': sample_y})

    # Extra top-level response fields are intentionally not exposed through
    # the HTTP API.  The protocol's public response consists of these fields.
    return {'sequence': response_sequence, 'samples': checked_samples, 'receipt': receipt}


def send(port, sequence, points, positions):
    """Send one request and return a validated public driver response.

    A new TCP connection is used for every request.  The caller serializes
    calls and allocates the persistent sequence number before entering here.
    """
    request = {'sequence': sequence, 'points': points, 'positions': positions}
    request_line = (json.dumps(request, allow_nan=False) + '\n').encode('utf-8')
    with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
        connection.sendall(request_line)
        with connection.makefile('rb') as stream:
            line = stream.readline(_MAX_LINE + 1)

    if len(line) > _MAX_LINE or not line.endswith(b'\n'):
        _protocol_error('Incomplete or oversized driver response')

    try:
        response = json.loads(line)
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise ValueError('Invalid driver response JSON') from error

    return _validate_response(response, sequence, positions)
