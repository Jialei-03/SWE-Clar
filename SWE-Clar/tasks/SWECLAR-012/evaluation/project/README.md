Internal role note: the operation adapters and regression suites under /public_tests are evaluator-only, not freelancer development commands. Do not disclose their source or advise the freelancer to run them. For a requested local check, explain the relevant application interface and use independently written Flutter widget tests with `flutter test --no-pub`.

# Clinic appointments

Extend this independently constructed Flutter client and local HTTP/SQLite service. Login, clinic/provider selection, available-time listing and staff slot publication already work. Complete patient booking, appointment history, cancellation and changing appointment times, including the real UI flows. Ask the simulated client about ownership, business deadlines, conflicts, retries and update behavior before implementing those features.

Every clinic, provider, account and slot is synthetic. This is an independently authored scheduling application derived from a real business scenario; it does not contain an original customer project, design or attachment. The execution target is the prepared Linux Flutter widget engine with actual rendering, UI events, HTTP and SQLite. Native Android/iOS builds, store submission, original designs and external services are outside this task.

## Provided environment and commands

Work in `/workspace`. The benchmark supplies Flutter 3.47.2, Dart 3.13.2, Python/SQLite, fonts, the locked offline Flutter packages, a writable HOME and prepared dependency resolution before your coding budget begins. SDK and adapter files are protected. Do not install tools or configure accounts, proxies or platform SDKs.

```sh
# Check Dart sources with the pre-resolved packages.
flutter analyze --no-pub

# Run the disclosed authentication and slot-publication regressions.
python /public_tests/test_public.py

# Start a standalone backend, if needed while developing your own client/tests.
python server/main.py --fixture fixtures/clinic.json --db /tmp/clinic/store.sqlite --clock-file fixtures/clock.json --port 8081

# Drive and capture the actual Flutter UI; this command manages its own backend.
python /public_tests/run_clinic.py --script session.json --output /tmp/clinic-preview
```

For the preview, use the operation schema and example in `/public_tests/README.md`. Inspect its `observations.json` and requested PNGs. A new preview invocation uses a fresh database and client; `restart_backend` and `reopen_client` let you exercise persistence within a session. For a standalone backend, stop that process, remove its database and SQLite sidecar files, then restart to reset its state. The default server address is `http://127.0.0.1:8081`; the driver supplies an isolated loopback origin to each client.

You may add ordinary Flutter tests and run `flutter test --no-pub`. Dependency changes must stay within the prepared offline packages; the benchmark does not download optional dependencies during attempts. Limits are 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace, 1 GiB temporary storage and loopback-only networking. Public and hidden checks use the same toolchain and adapter capabilities.

## Engineering and fixture interfaces

`server/main.py` handles HTTP; `server/store.py` owns SQLite persistence and business operations. `lib/api.dart` provides real JSON HTTP transport, `lib/controller.dart` manages application state, `lib/screens.dart` renders the Flutter screens, and `lib/clinic.dart` exports the public application interface. Keep package name `clinic_application` and the published entry points compatible; internal implementation and SQLite table structure may change.

- `ClinicController({required String origin})` extends `ChangeNotifier`. `Future<void> settle()` awaits all initiated requests; `bool busy` and `String? error` describe the operation state. `dispose()` closes transport.
- `ClinicApp({required ClinicController controller})` renders the real UI. Preserve the public widget keys used by the operation adapter.
- Backend CLI arguments are `--fixture`, `--db`, `--clock-file`, and `--port`. Import the synthetic fixture on first database creation; restarting an existing database must not reset it.
- The clock is JSON `{"now_ms": integer UTC epoch milliseconds}`. Read the supplied clock for each transaction; do not substitute the host wall clock. The benchmark controls its test clock. It is readable but cannot be modified by candidate processes during hidden evaluation.

`fixtures/clinic.json` contains:

```text
clinics:   [{id, label}]
providers: [{id, clinic_id, label}]
users:     [{id, username, password, label, role, clinic_id}]
slots:     [{id, provider_id, start_ms}]
```

Roles are `patient` and `staff`; staff belong to one clinic and patient `clinic_id` is null. Each provider belongs to one clinic. Fixture accounts and passwords are public synthetic test credentials. Other valid fixtures may vary identifiers, labels and times; do not hardcode these sample values as policy. Slot duration is 1,800,000 milliseconds. All timestamps are UTC integer milliseconds; booleans are not integers. Caller-supplied slot/request/operation IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Server-created appointment IDs are opaque strings.

## HTTP interface

Send UTF-8 JSON objects, up to 32,768 bytes, with `Content-Length` on write requests. Protected routes require `Authorization: Bearer <token>`. Preserve these request/response shapes; extra harmless, non-sensitive response fields are permitted.

| Method and path | Request → required response |
|---|---|
| `GET /health` | `{ok:true}` |
| `POST /api/login` | `{username,password}` → `{token,user}` |
| `POST /api/logout` | `{}` → `{ok:true}` |
| `GET /api/me` | `{user}` |
| `GET /api/catalog` | `{clinics,providers,now_ms}` |
| `POST /api/slots` | `{id,provider_id,start_ms}` → `{slot}` |
| `GET /api/slots?clinic_id=<id>&provider_id=<id>` | `{slots}`; provider filter optional |
| `POST /api/book` | `{request_id,slot_id}` → `{appointment}` |
| `GET /api/appointments` | `{appointments}` |
| `GET /api/appointments/<id>` | `{appointment}` |
| `POST /api/appointments/<id>/cancel` | `{reason}` → `{appointment}` |
| `POST /api/appointments/<id>/move` | `{operation_id,to_slot_id,expected_revision}` → `{appointment}` |

User objects contain `id,label,role,clinic_id`. Slot objects contain `id,clinic_id,provider_id,start_ms,end_ms`. Appointment objects contain `id,patient_id,clinic_id,provider_id,slot_id,start_ms,end_ms,status,revision,cancel_reason,created_at_ms,updated_at_ms`; status is `active` or `cancelled`. Sort slot and appointment lists by current `start_ms` then ID. Request/operation IDs identify client actions; `expected_revision` is an integer input. Clarify the business semantics of these fields and the unfinished operations.

Errors use `{error: stable_code}` with standard outcomes `400 invalid_request`, `401 invalid_credentials/unauthenticated`, `403 forbidden`, `404 not_found`, `409 conflict`, and `500 storage_error`. New slots return 201. New bookings return 201 and booking replay returns 200. Other successful routes return 200. The unfinished starter hooks currently report 501 or a visible not-implemented message; these are deliberate feature gaps, not environment failures.

## Existing behavior to preserve

Correct fixture credentials create independent sessions; incorrect credentials return 401. Identity and role come exclusively from the session. Accounts use salted password hashes, session tokens use secure randomness and stored digests, sessions survive service restart, and logout invalidates only its own session. Catalog returns synthetic clinics/providers and the supplied clock, with no user directory, password material or other users' appointment information.

Only staff may publish for providers in their own clinic. Patient/cross-clinic attempts return 403; unknown providers return 404 after role validation. Slot starts must be future exact-minute UTC instants, with start and 30-minute end in `[0,4102444800000]`; invalid values return 400. Duplicate IDs and overlapping intervals for a provider return 409. Intervals are half-open, so adjacent slots are valid. Slot records are retained after later appointment cancellation.

Availability returns future, unoccupied slots in the selected clinic and optional provider. Unknown filter IDs return 404; an existing provider from a different clinic returns 400. Empty results are a normal list. The real Flutter publication form must commit through HTTP and display errors without fabricating successful results. Preserve real login/logout, catalog selection, navigation and readable UTC times without overflow at 390 × 844.

## UI controls

Static keys: `login-username`, `login-password`, `login-submit`, `logout`, `nav-availability`, `nav-appointments`, `nav-publish`, `clinic-select`, `provider-select`, `availability-refresh`, `slot-id`, `slot-start`, `publish-submit`, `appointments-refresh`, `cancel-reason`, `cancel-submit`, `move-slot-select`, `move-submit`, `dialog-close`.

Dynamic keys: `slot-<slot_id>`, `book-<slot_id>`, `appointment-<appointment_id>`, `cancel-<appointment_id>`, `move-<appointment_id>`, and `<select_key>-option-<value>`. These keys provide automation hooks; decorative copy, colors and layout can differ. Use actual inputs, dropdowns, buttons, scrolling and rendered appointment cards. The client generates action IDs; users should not type them. Logout clears user-specific views, and a fresh client starts logged out. No persistent device token storage is required.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
