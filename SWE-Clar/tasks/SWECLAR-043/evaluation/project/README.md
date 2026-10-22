# Delivery workbench

Complete `apply_delivery_event(order: dict, event: dict) -> dict` in `solution.py`. The provided local HTTP server, SQLite order storage, proof-file storage and browser form work already. Preserve their functionality.

## Prepared environment and commands

Use `/workspace` with the supplied `python-web` runtime. Python, SQLite and browser tooling are prepared before the task; no installation, internet, credentials or external service is needed. Resources: 2 CPU, 2048 MiB memory, 256 processes, 256 MiB workspace. Local loopback networking is available.

- Start: `python server.py --port 8080 --data runtime`; open `http://127.0.0.1:8080/`.
- Public check: `python /public_tests/test_public.py`.
- Reset: stop the server and run `python -c "import shutil; shutil.rmtree('runtime', ignore_errors=True)"`, then restart.
- Stop: Ctrl-C. Adapter errors appear in terminal output and JSON responses.

The public check uses temporary data. Runtime files must not be included in code delivery. Keep entry-point filenames and public interfaces; internal implementation is free.

## Record and HTTP interfaces

An order is a JSON object with `id`, `status`, `history` (list) and optional unrelated metadata. Direct function calls may omit `id` or `history`; a missing history starts as an empty list on successful transitions. Events have `type`: `assign`, `pickup`, `deliver` or `reject`. Other possible fields are `receiver`, `photo`, `signature`, `reason`. Proof references are opaque strings; file storage is handled separately. Ask the client about validation policies.

Return the resulting order. Successful history entries have at least `type` (event type) and `status` (resulting status). Extra nonconflicting metadata is allowed. Errors use `error: {code: <nonempty string>}` alongside unchanged order fields; any nonempty error code is accepted. Stored proof uses `proof.receiver`, `proof.photo` and `proof.signature`; an unused proof field may be absent or null. Stored rejection uses `rejection.reason`.

The supplied server manages one synthetic order `parcel-demo`:

- `GET /api/order` returns persisted state.
- `POST /api/event` accepts event JSON, invokes the workflow, persists successful results and returns the result. Business errors use HTTP 200 with `error.code`; malformed transport requests use HTTP 400.
- `POST /api/proofs` accepts `{"data": "<base64 bytes>"}` and returns HTTP 201 with `{"ref": "/files/<opaque token>"}`. Nonempty files up to 1 MB are supported. Original filename and metadata are not stored separately.
- `GET <ref>` returns exact uploaded bytes. Files and orders survive restart with the same data directory.
- `GET /` serves the form, which uploads selected files and applies events without manual API calls.

The workflow is also tested with synthetic references directly; do not require every reference to exist on disk. Camera capture, signature recognition, authentication and external delivery integration are outside scope.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
