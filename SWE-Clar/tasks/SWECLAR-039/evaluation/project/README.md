# Framed device monitor

Complete this running local device-monitoring application. It already has a browser dashboard, binary-framed TCP client, runnable synthetic peer, device discovery and SQLite state storage. Finish pairing/connection policy, command/telemetry handling and responsive layout after clarifying the client's choices. This is independently reconstructed device-integration software; it does not claim radio, GATT, mobile-framework or proprietary-hardware compatibility.

## Prepared environment

The benchmark supplies Python 3.12, SQLite, Playwright/Chromium and isolated loopback networking before your attempt. No dependencies, real device, account, cloud service or external network are needed. Work in `/workspace`; limits are 2 CPUs, 2 GiB memory, 256 processes and 512 MiB workspace.

Start: `python server.py --host 0.0.0.0 --port 8000 --db /tmp/devices.sqlite`. Port 0 chooses a free port; the first stdout line is `{"port":<integer>}`. By default a working synthetic peer starts as a child and stops with the app. Its demo devices are `SENSOR-A` and `SENSOR-B`, advertising `capture.v1`; their initial fictional pairing codes are `DEMO-PAIR-A` and `DEMO-PAIR-B`. Its consumed-code/paired-device state is stored beside the selected database without storing submitted pairing codes. Reset by choosing a fresh database path. The manager may prepare a separate peer and supply `--peer-port <port>`; tests provide this service before starting the app. Device identifiers and peer receipts in evaluation are synthetic and may differ from the demo.

Public tests: `python -I /public_tests/test_public.py`. Syntax check: `python -m py_compile server.py controller.py wire.py peer.py`. There is no build step. The protocol is already executable; do not replace real peer communication with caller-supplied device/telemetry lists.

## Public APIs

All POSTs accept JSON objects, 1..65536 UTF-8 bytes. Invalid request shapes return 400 `{error:"invalid_request"}`. Unknown routes return 404. Each device, command and packet ID is a string matching `[A-Za-z0-9_-]{1,64}`. Local inputs contain no original customer identifiers.

- `GET /api/state`: `{devices,paired,connected,commands,telemetry}`. Devices contain `{device_id,name,services}`; paired is a list of device IDs; connected is one ID or null. Commands contain `{device_id,command_id,name,result}`; telemetry contains `{device_id,packet_id,data}`. Initial state has empty lists and null connection. Pairing/history are stored in SQLite; exact lifecycle and restart behavior are client decisions.
- `POST /api/scan`, `{service:<string of length 1..64>}`: query the prepared peer. Collapse duplicate advertisements by stable ID, keeping the latest advertised fields in first-seen ID order; then retain only devices whose latest services include the requested exact service string. Replace the discovery list on each successful scan. Reject malformed peer advertisements with 502. Do not sort results or retain stale advertisements from earlier scans.
- `POST /api/pair`, `{device_id,code:<string of length 1..64>}`; `POST /api/connect`, `{device_id}`; `POST /api/disconnect`, `{}`: perform lifecycle operations and return complete state. Eligibility, repeated operations, code consumption and retained state can be clarified.
- `POST /api/command`, `{device_id,command_id,name}`: send an operation and return `{result:<peer result object>}`. Clarify allowed commands, connection requirements, retries and telemetry filtering. No caller-supplied telemetry is accepted by the HTTP API.

Workflow denials return 409 `{error:<code>}`; peer denial (`ok:false`) returns 403 `{error:"peer_denied"}`; framing, connection, timeout or peer-schema failures return 502 `{error:"peer_failure"}`. Public command/packet schemas and these error categories are fixed. Ask which state should survive each failure.

`GET /` provides real controls. Keep `#service`, `#scan`, device buttons with `data-device` inside `#device-list`, readonly selection `#device`, password field `#pair-code`, buttons `#pair`, `#connect`, `#disconnect`, and current connection text `#connection`. Keep `#command-id`, `#command-name`, `#send`, `#command-result`, and telemetry list `#telemetry`, whose rows use `data-device` and `data-packet`. Render names and telemetry as text, never untrusted HTML. Keep `#device-panel`, `#telemetry-panel` and their parent `#workspace` for layout checks. Other styling and markup can change. Clicking a device selects it; successful operations refresh actual server state. Resizing must not send workflow commands or erase state.

## Framed peer protocol

Each message is a four-byte unsigned big-endian payload length followed by that many UTF-8 JSON bytes. Valid payload lengths are 1..65536; JSON numbers must be finite. TCP can fragment headers/bodies or combine multiple frames. Read exact frame lengths, not a single recv call. A new connection per operation is allowed. Socket timeout is 2 seconds. The manager supplies a functioning peer; evaluation also sends intentional protocol-fault responses to check recovery.

Requests use these fields:

```text
{op:"scan",service}
{op:"pair",device_id,code}
{op:"connect",device_id}
{op:"disconnect",device_id}
{op:"command",device_id,command_id,name}
```

Every response is a JSON object with boolean `ok`. A denial has `ok:false`. Scan success adds `devices`, an array of `{device_id,name:<string>,services:<array of strings>}`. Other lifecycle successes need only `ok:true`. Command success adds `command_id`, `result` (a JSON object), and integer `packet_count` in 0..64. It is immediately followed by exactly that many telemetry frames, each `{device_id,packet_id,data:<JSON object>}`. Nested JSON, Unicode and arbitrary data keys are allowed. Extra fields may be ignored. A successful command's complete result and all packets must be received and validated before committing it to history. Peer output must not be replaced with hard-coded acknowledgements or locally invented telemetry.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
