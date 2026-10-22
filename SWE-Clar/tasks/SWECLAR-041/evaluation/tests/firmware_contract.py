import json
import os
import struct
import sys
import time
from pathlib import Path
sys.path.insert(0, '/opt/sweclar'); sys.path.insert(0, '/public_tests')
from harness import Board, Bus, Firmware
from preflight import preflight
from test_public import interface, shutdown, registration
sys.path.insert(0,str(Path(__file__).resolve().parent))
from short_write_support import ShortWriteFirmware,FaultUnavailable
PROJECT = Path(os.environ.get('SWECLAR_PROJECT_DIR', '/workspace'))


def gpio(t, level): return struct.pack('!BIB', 1, t, level)
def beacon(t): return struct.pack('!BI', 2, t)
def health(t, rssi, channel, bandwidth): return struct.pack('!4sIhBB', b'HT01', t, rssi, channel, bandwidth)


def timing():
    with Board() as board, Bus() as bus, Firmware(PROJECT, board, bus) as app:
        assert board.drain() == [gpio(0, 1), beacon(0)]
        app.command('advance 99'); assert board.drain() == []
        app.command('network 0'); app.command('advance 100'); assert board.drain() == [gpio(100, 0)]
        app.command('advance 1050')
        assert board.drain() == [gpio(t, (t // 100 + 1) % 2) for t in range(200, 1001, 100)] + [beacon(1000)]
        app.command('network 1'); assert board.drain() == []
        app.command('advance 1549'); assert board.drain() == []
        app.command('network 1'); app.command('advance 1550'); assert board.drain() == [gpio(1550, 0)]
        app.command('registered'); app.command('registered')
        app.command('advance 2050'); assert board.drain() == [gpio(2050, 1)]
        app.command('advance 2550'); assert board.drain() == [gpio(2550, 0)]
        app.command('broker 1'); app.wait_status(broker=True)
        assert board.drain() == [gpio(2550, 1)]
        app.command('advance 5550'); assert board.drain() == []
        app.command('broker 0'); app.command('advance 6050'); assert board.drain() == [gpio(6050, 0)]
        app.command('network 0'); assert board.drain() == [gpio(6050, 1)]
        app.command('advance 6150'); assert board.drain() == [gpio(6150, 0)]
        app.command('advance 6150'); assert board.drain() == []
    # Check mode anchoring at several non-round offsets, independent of the main scenario.
    for offset in (37, 163, 719):
        with Board() as board, Bus() as bus, Firmware(PROJECT, board, bus) as app:
            app.command(f'advance {offset}'); board.drain()
            app.command('network 1'); board.drain()
            app.command(f'advance {offset+499}'); board.drain()
            app.command('network 1'); app.command(f'advance {offset+500}')
            assert [x for x in board.drain() if x[:1] == b'\x01'] == [gpio(offset+500, 0)]


def telemetry():
    with Board() as board, Bus() as bus, ShortWriteFirmware(PROJECT,board,bus) as app:
        app.command('network 1');app.command('broker 1');app.wait_status(broker=True)
        offset=len(app.fault_log())
        app.command('health -37 7 40')
        # No telemetry is a candidate behavior failure, not proof the injector is unavailable.
        assert bus.wait_records(1)==[health(0,-37,7,40)]
        app.require_fault('SHORT',after=offset)
        app.mode.write_text('B')
        app.command('health -99 2 20');app.require_fault('BLOCK')
        assert len(bus.records)==1
        # One eligible frame has an unsent suffix; another is wholly queued.
        app.command('health -98 3 80');app.command('broker 0')
        app.wait_status(broker=False,pending=False);app.mode.write_text('S')
        app.command('broker 1');app.wait_status(broker=True)
        app.command('advance 17');app.command('health -12 11 80')
        expected=[health(0,-37,7,40),health(17,-12,11,80)]
        assert bus.wait_records(2)==expected
        time.sleep(.03);assert bus.records==expected
    with Board() as board, Bus(auto_ack=False) as bus, Firmware(PROJECT, board, bus) as app:
        app.command('health -60 3 20'); app.command('network 1')
        app.command('health -61 4 40'); app.command('broker 1'); app.wait_status(pending=True)
        app.command('health -62 5 80'); app.command('advance 321')
        assert bus.records == []
        bus.release.set(); app.wait_status(broker=True)
        samples = [(-127, 1, 20), (0, 14, 80), (-52, 7, 40), (-52, 7, 40)]
        for r, c, b in samples: app.command(f'health {r} {c} {b}')
        expected = [health(321, *s) for s in samples]
        assert bus.wait_records(4) == expected
        app.command('registered'); app.command('advance 432')
        app.command('health -1 9 20'); expected.append(health(432, -1, 9, 20))
        assert bus.wait_records(5) == expected
        bus.disconnect(); app.wait_status(broker=False, pending=False)
        app.command('health -3 2 40'); app.command('broker 1'); app.wait_status(broker=True)
        app.command('health -4 3 80'); expected.append(health(432, -4, 3, 80))
        assert bus.wait_records(6) == expected
        app.command('network 0'); app.command('health -5 4 20')
        app.command('network 1'); assert app.command('status')['broker'] is False
        app.command('broker 1'); app.wait_status(broker=True)
        app.command('health -6 5 40'); expected.append(health(432, -6, 5, 40))
        assert bus.wait_records(7) == expected
        time.sleep(0.03); assert bus.records == expected


def safe_errors():
    with Board() as board, Bus() as bus, Firmware(PROJECT, board, bus) as app:
        board.drain(); before = app.command('status')
        assert app.command('broker 1', ok=False)['error'] == 'network_down'
        assert app.command('status') == before and board.drain() == [] and bus.hellos == []
        app.command('network 1'); app.command('broker 1'); app.wait_status(broker=True)
        app.command('advance 321'); board.drain(); before = app.command('status')
        invalid = ['', 'bogus', 'status extra', 'registered extra', 'quit extra', 'network 2',
                   'broker -1', 'network true', 'advance', 'advance -1', 'advance 320',
                   'advance 10322', 'advance 86400001', 'advance +322', 'advance 3.2',
                   'advance 99999999999999999999999999', 'health -128 1 20', 'health 1 1 20',
                   'health -1 0 20', 'health -1 15 20', 'health -1 1 21', 'health -1 1',
                   'health -1 1 20 extra', 'health -1 1.0 20', 'health -1 1 +20',
                   'x'*257, 'x'*4096, 'status'+' '*251, '网络 1', 'status\x00']
        for line in invalid:
            assert app.command(line, ok=False)['error'] == 'invalid_command', repr(line)
            assert app.command('status') == before, repr(line)
            assert board.drain() == [] and bus.records == [], repr(line)
        registration(app.registration_port)
        app.command('status\r'); app.command('status'+' '*250)
        for _ in range(4): app.command('network 1'); app.command('broker 1')
        assert app.command('status') == before and bus.hellos == [b'HB01']
        app.command('health -44 6 40'); assert bus.wait_records(1) == [health(321, -44, 6, 40)]
        app.command('broker 0'); app.command('broker 0'); app.wait_status(broker=False, pending=False)
    with Board() as board, Bus(auto_ack=False) as bus, Firmware(PROJECT, board, bus) as app:
        app.command('network 1'); app.command('broker 1'); app.wait_status(pending=True)
        for _ in range(4): app.command('broker 1')
        app.command('network 0'); app.wait_status(network=False, broker=False, pending=False)
        bus.release.set(); time.sleep(0.03)
        assert len(bus.hellos) <= 1
        app.command('network 1'); assert app.command('status')['broker'] is False
        app.command('broker 1'); app.wait_status(broker=True)


def main():
    try: prepared = preflight()
    except Exception as error:
        print(json.dumps(dict(harness_ok=False, infrastructure_errors=[str(error)], results=[]))); return 2
    results = []
    for i, test in enumerate([interface, shutdown, timing, telemetry, safe_errors], 1):
        try:
            test(); results.append(dict(ru_id=f'RU-{i:03d}', passed=True))
        except FaultUnavailable as error:
            print(json.dumps(dict(harness_ok=False,infrastructure_errors=[str(error)],results=results)));return 2
        except (AssertionError, KeyError, TypeError, ValueError, ConnectionError, TimeoutError) as error:
            results.append(dict(ru_id=f'RU-{i:03d}', passed=False, detail=type(error).__name__+': '+str(error)))
    print(json.dumps(dict(harness_ok=True, preflight=prepared, results=results))); return 0


if __name__ == '__main__': raise SystemExit(main())
