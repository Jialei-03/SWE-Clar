# Clinic operation and preview adapter

Run from `/workspace` inside the prepared environment:

```sh
python /public_tests/test_public.py
python /public_tests/run_clinic.py --script session.json --output /tmp/clinic-preview
```

The first command checks the initially disclosed authentication and slot-publication behavior. It does not require unfinished booking, cancellation or rescheduling to pass. The second command drives actual Flutter widgets and HTTP services and writes `observations.json` and requested PNG screenshots. Successful transport is not a business correctness judgment.

Example `session.json`:

```json
{
  "operations": [
    {"op":"mount"},
    {"op":"enter_text","key":"login-username","text":"patient.one"},
    {"op":"enter_text","key":"login-password","text":"synthetic-patient-one"},
    {"op":"tap","key":"login-submit"},
    {"op":"capture","name":"availability.png"}
  ]
}
```

The adapter starts its own isolated service and database; no separately running backend is needed for this preview. With no `fixture` or `now_ms`, it reads the project's synthetic `fixtures/clinic.json` and `fixtures/clock.json`. A new invocation starts a fresh database and unauthenticated client. Use an empty output directory. All addresses are local and each instance has its own ports.

| Operation | Fields and behavior |
|---|---|
| `mount` | Render `ClinicApp` in the actual Flutter engine; default viewport 390 × 844. |
| `viewport` | `width`, `height`; supported logical size 240–1600 × 320–1600. |
| `enter_text` | `key`, `text`; edit the real keyed text input. |
| `tap` | `key`; scroll into view and deliver a real tap. |
| `select` | `key`, `value`; open the actual dropdown and select its keyed option. |
| `inspect` | Observe mounted widget text, keyed subtrees, controls and the public controller's error/busy state. |
| `capture` | `name`; a distinct PNG basename; export the actual rendered frame. |
| `reopen_client` | End the Flutter process, start a new one, and mount the app; backend data remains. |
| `restart_backend` | Stop and restart the service using the same database, fixture and clock. |
| `set_clock` | `now_ms`; atomically update the benchmark-managed clock. |
| `api` | `method`, `path`, optional `body` and bearer `token`; return actual `status` and JSON `body`. |
| `parallel_api` | `requests`; 1–16 API request objects started concurrently; results remain in input order. |
| `drop_next_response` | `path`, optional `method` (default `POST`) and `hold` (default `false`); forward one matching UI request to the real backend, then lose its completed response. |
| `release_response` | For a held response, optional `drop` (default `false`); wait for the request to reach the backend, then release or lose the response. |
| `storage_readonly` | `value`; set or restore actual Unix write permissions on this instance's SQLite directory/files. |

UI operations normally await the controller's pending requests. Use `wait:false` on taps or inspections when intentionally holding a response; call `release_response` before waiting for that operation to finish. This allows observation of pending buttons, double taps and transport failures. Response faults apply only to UI traffic through the adapter's proxy; explicit `api` operations go directly to the backend. `storage_readonly` affects both paths. These capabilities are public and identical during development and hidden evaluation.

An operation may include `save_as` to save its result. Later operations can reference it using `{"$ref":"name.body.token"}` or join strings with `{"$concat":["/api/appointments/",{"$ref":"booking.body.appointment.id"}]}`. References can access only prior results. They are resolved by the manager, not by candidate code.

Only the current UI operation is sent to the Flutter process. Future commands, business expected values and hidden assertions stay in the calling manager. Protected read-only adapter files and SDK code provide the observation mechanism; candidate code owns its project and application storage. In hidden evaluation, the clock's file and parent directory are manager-owned so candidate processes cannot replace either. Password fields are redacted from widget observations. HTTP traces contain the synthetic requests supplied in that session and must be treated as session data.

The manager runs `/opt/sweclar/preflight.py` plus `/public_tests/preflight.py --prepare-workspace` before candidate work. The latter independently exercises a separate synthetic Flutter/HTTP/SQLite fixture and prepares the provided workspace's locked offline dependencies. It never uses the candidate application as proof that the environment works. Baseline dependency preparation and candidate business regressions are recorded separately.

Per session: candidate commands use UID 1000 with no Linux capabilities; 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace and 1 GiB temporary storage. A UI operation has a 35-second transport limit, a pending controller request is awaited for at most 20 seconds, and a held proxy response must be released within 20 seconds. These are generous execution limits, not performance scores. A missing protected adapter/tool or independent preflight failure is an environment error. An application that cannot build, start, respond or render under the verified interface fails the corresponding candidate check.
