# Portable controller firmware

Refactor and complete this running C++ controller. It has a poll-based event loop, serial command parser, registration listener, virtual-board GPIO/beacon transport and asynchronous telemetry-bus client. Complete the LED policy, health publication and error-handling behavior after clarification. This independently reconstructed firmware exercise uses a synthetic board and protocol, and makes no ESP32, BLE, Wi-Fi-radio or MQTT compatibility claim.

## Prepared build and run

The benchmark provides GCC 14.2.0, Make, Python 3.11 and loopback networking in an immutable Linux AMD64 environment. No SDK, physical board, packages, cloud account or downloads are needed during the attempt. Work in `/workspace`, run `make`, then `build/firmware --board-port <prepared UDP port> --bus-port <prepared TCP port>`. The manager prepares both virtual-board receivers before launch. Public tests start isolated receivers automatically: `python -I /public_tests/test_public.py`. `make clean` removes only the local build directory. Restarting the process starts a fresh controller and virtual clock.

Resources are 2 CPUs, 2 GiB memory, 256 processes and 512 MiB workspace. The published regression harness allows 30 seconds to build this small project. The benchmark runs its independent compiler/socket preflight before candidate work. Build errors introduced by candidate code are evaluated as candidate failures; missing tools are benchmark infrastructure failures.

Keep the executable name and the two port arguments. Source structure can change. The initial stdout line is JSON `{"registration_port":<port>}`, naming the controller's automatically assigned loopback TCP registration listener. Each subsequent newline-terminated input command produces one newline-terminated JSON response. Keep diagnostic output on stderr. stdin is a virtual serial input, not a real radio; the other interfaces below must perform actual socket I/O.

## Serial input and state

Commands are ASCII whitespace-separated tokens, at most 256 bytes before LF. CRLF is accepted. Decimal integers use an optional leading minus but no plus or fraction. The public grammar is:

```text
status
network 0|1
broker 0|1
registered
advance <absolute_time_ms>
health <rssi> <channel> <bandwidth>
quit
```

`advance` uses a deterministic virtual clock: time starts at 0, cannot decrease, cannot exceed 86400000, and each increase is at most 10000 ms. No real-time sleeping is required to simulate elapsed time. RSSI is -127..0, channel 1..14, bandwidth is one of 20, 40, 80. These interface ranges are public. All valid commands return `{ok:true}` except `status`, which also returns integer `time`, boolean `network`, `broker`, `pending`, `registered`, integer `led_level` (0 or 1), and `registration_port`. The detailed invalid/repeated-event policy is a client decision. `quit` acknowledges then exits with code 0.

`network` supplies the virtual network-link input. `broker 1` requests an asynchronous local bus handshake; `broker 0` closes it. It must remain possible to read serial commands and serve registration while a peer delays its handshake. `broker` becomes true only after the actual prepared peer confirms the handshake. Initial network/broker/pending/registered are false.

Initially the actual registration listener accepts connections, writes ASCII `SETUP\n` and closes each client. A registration beacon is sent to the virtual board at time 0 and every 1000 virtual milliseconds while registration is active. `registered` closes that listener and stops future beacons, preserving connectivity and the current LED schedule. Its repeated use is harmless. Do not substitute a status flag for closing the actual listener.

## Virtual board and telemetry-bus bytes

All receivers run on `127.0.0.1`; the manager passes their dynamic ports. All multibyte integers use network (big-endian) byte order.

The virtual board receives UDP datagrams:

- GPIO: one byte `0x01`, four-byte unsigned virtual timestamp, one byte digital level 0 or 1 (six bytes total).
- Registration beacon: one byte `0x02`, four-byte unsigned virtual timestamp (five bytes total).

Emit the initial GPIO high level at time 0. Subsequent GPIO output records physical level changes, not a text label such as fast_blink. Exact LED phases and timing are available through clarification. Emit each crossed scheduled event when advancing time, with its scheduled timestamp; if a GPIO edge and beacon share a timestamp, emit the GPIO edge first. No task output is accepted merely because the process reports a mode or transmission counter.

The telemetry bus is a persistent TCP connection. Send four bytes `HB01` on connection, then accept exactly four bytes `OK01`, which may arrive fragmented. Do not treat a connection or a partial/bad acknowledgement as ready. A remote close invalidates bus readiness. No other inbound data follows a successful acknowledgement. A new explicit `broker 1` can retry after closure or rejection; the peer may intentionally withhold its acknowledgement to test event-loop responsiveness.

A health frame is exactly 12 bytes: ASCII `HT01`, four-byte unsigned virtual timestamp, two-byte signed RSSI in two's-complement form, one-byte channel, one-byte bandwidth. The publication eligibility, queue/discard behavior and repeat semantics are client decisions. Handle partial TCP writes; the protected receiver observes the actual bytes. Reconnecting must not replay data from a previous closed connection.

The manager prepares the board and bus fixtures and supplies synthetic inputs. The task never needs customer firmware, original topics/identifiers, physical GPIO or external services.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
