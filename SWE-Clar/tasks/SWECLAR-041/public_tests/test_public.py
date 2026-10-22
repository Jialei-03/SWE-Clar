"""Public executable-interface regression; no hidden client policy."""
import os
import socket
import struct
import sys
from pathlib import Path
sys.path.insert(0, '/opt/sweclar')
from harness import Board, Bus, Firmware
from preflight import preflight
PROJECT = Path(os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))


def registration(port):
    with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
        data = b''
        while True:
            part = client.recv(64)
            if not part: break
            data += part
        assert data == b'SETUP\n', data


def closed(port):
    try:
        client = socket.create_connection(('127.0.0.1', port), timeout=1)
    except ConnectionRefusedError:
        return
    client.close()
    raise AssertionError('Registration listener remains open')


def interface():
    with Board() as board, Bus(auto_ack=False) as bus, Firmware(PROJECT, board, bus) as app:
        initial = app.command('status')
        assert initial == dict(ok=True, time=0, network=False, broker=False, pending=False,
                              registered=False, led_level=1, registration_port=app.registration_port)
        assert board.drain() == [struct.pack('!BIB', 1, 0, 1), struct.pack('!BI', 2, 0)]
        registration(app.registration_port)
        app.command('network 1'); app.command('broker 1')
        app.wait_status(network=True, broker=False, pending=True)
        app.command('advance 55')
        registration(app.registration_port)
        bus.release.set()
        app.wait_status(broker=True, pending=False)
        assert bus.hellos == [b'HB01']
        bus.disconnect(); app.wait_status(broker=False, pending=False)
        app.command('quit'); assert app.process.wait(timeout=2) == 0
    with Board() as board, Bus(ack=b'NO01') as bus, Firmware(PROJECT, board, bus) as app:
        app.command('network 1'); app.command('broker 1')
        # Synchronize with the peer before checking rejection, avoiding an initial-state pass.
        import time
        deadline = time.monotonic() + 2
        while not bus.hellos and time.monotonic() < deadline: time.sleep(0.005)
        assert bus.hellos == [b'HB01']
        app.wait_status(broker=False, pending=False)
        registration(app.registration_port)


    # A peer that supplies only the valid prefix never completes the handshake.
    # Repeated serial requests must remain responsive and must not report readiness.
    with Board() as board, Bus(ack=b'OK') as bus, Firmware(PROJECT, board, bus) as app:
        app.command('network 1'); app.command('broker 1')
        import time
        deadline = time.monotonic() + 2
        while not bus.hellos and time.monotonic() < deadline: time.sleep(0.005)
        assert bus.hellos == [b'HB01']
        for _ in range(20):
            time.sleep(0.005)
            state = app.command('status')
            assert state['broker'] is False and state['pending'] is True
        registration(app.registration_port)
        app.command('broker 0'); app.wait_status(broker=False, pending=False)


def shutdown():
    with Board() as board, Bus() as bus, Firmware(PROJECT, board, bus) as app:
        board.drain(); app.command('advance 2500')
        beacons = [x for x in board.drain() if x[:1] == b'\x02']
        assert beacons == [struct.pack('!BI', 2, t) for t in (1000, 2000)]
        app.command('network 1'); app.command('broker 1'); app.wait_status(broker=True)
        before = app.command('status'); board.drain()
        app.command('registered'); closed(app.registration_port)
        assert app.command('status') == dict(before, registered=True)
        assert board.drain() == []
        app.command('registered'); app.command('advance 6000')
        assert not any(x[:1] == b'\x02' for x in board.drain())
        assert app.command('status')['broker'] is True and bus.hellos == [b'HB01']
    with Board() as board, Bus(auto_ack=False) as bus, Firmware(PROJECT, board, bus) as app:
        app.command('network 1'); app.command('broker 1'); app.wait_status(pending=True)
        before = app.command('status'); app.command('registered'); closed(app.registration_port)
        assert app.command('status') == dict(before, registered=True)
        bus.release.set(); app.wait_status(broker=True)


def run():
    interface(); shutdown()
    print('Public firmware interface and registration checks passed')


if __name__ == '__main__':
    preflight(); run()
