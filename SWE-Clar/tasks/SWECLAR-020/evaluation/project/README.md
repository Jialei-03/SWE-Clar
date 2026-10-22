# Attendance workspace


Use the prepared `python-web` Linux AMD64 environment: Python 3.12, SQLite, Chromium 140 and Playwright 1.55. No downloads or accounts are needed. The benchmark prepares synthetic read-only `/workspace/dev_runtime/accounts.json` and a separate-UID HTTP reader simulator at `http://127.0.0.1:8081` before candidate budget. Candidate tools and browser run as UID1000 without capabilities; simulator UID2000 cannot read private tests. Candidate can use documented simulator HTTP endpoints but cannot modify its code or storage. Hidden evaluation uses the same service with fresh state. The framework supplies a loopback network, 2 CPUs, 2048 MiB memory, 256 PIDs, 512 MiB workspace and 1024 MiB temporary storage; each evaluation has 300 seconds.

Work in `/workspace`. Build: `python -m compileall -q server.py store.py reader.py`. Start: `python server.py --host 0.0.0.0 --port 8080 --db /workspace/data/attendance.sqlite3 --fixture /workspace/dev_runtime/accounts.json --reader http://127.0.0.1:8081`. Visible regressions: `python /public_tests/test_public.py`, using disposable copies, reader namespaces and databases. Stop the server, remove `/workspace/data`, and restart to reset application state; ordinary server restart preserves it. An application reset does not need to reset the reader; newly created reading IDs are unique. Environment preflight is independent of candidate code. A prepared sample reading can be generated with the documented simulator HTTP interface; candidate never needs to install hardware drivers.

The supplied project provides account login, scoped student roster, tag resolution and deliberate reading previews/pending scans. Complete confirmation authorization, collection checks, sequence/replay behavior and parent inbox delivery. All delivery interfaces below are public. Confirmation, collection, sequencing and delivery policies are clarifiable with the client. Internal database schema, ID generation, locking, code organization and unrelated presentation are unconstrained. Extra response metadata is allowed; unused request fields are ignored. Use real HTTP communication with the reader, real persistent application storage, and actual browser interactions.

### Prepared fixtures and reader protocol

The fixture contains `users`, `students`, `tags`, `devices`, and `guardians`. User fields: unique string `id`, `username`, `password`, `role` (`teacher`, `administrator`, `parent`), boolean `active`, `class_ids` array and `student_ids` array. Student: unique `id`, literal display `name`, `class_id`. Tag: unique `uid`, `student_id`, `active`. Device: unique `id`, `name`, `active`. Guardian: unique `id`, `name`, `student_ids`, `active`. Fixture IDs are nonempty strings, not guaranteed to follow a particular spelling. Account credentials are synthetic. Fixture arrays have stable ordering and references are valid. A user may belong to multiple classes/students; guardians need not have a user account. Multiple active tags may map to one student.

Reader simulator public HTTP:

- `GET /health` gives `{ok:true}`.
- `POST /readings` with `{uid,device_id,interaction,at}` creates an immutable synthetic reading, 201 `{reading}`. `uid` and `device_id` are nonempty strings up to100 characters; `interaction` is `tap` or `proximity`; `at` is a non-boolean JSON integer in0..2000000000 representing UTC Unix seconds. The simulator accepts unknown/inactive tags/devices so applications can test these cases. Missing/bad fields give400 `{error:{code:"invalid_request"}}`.
- `GET /readings/{id}` gives200 `{reading}` or404 `{error:{code:"not_found"}}`. Reading fields are unique opaque string `id`, `uid`, `device_id`, `interaction`, `at`.
- Responses allow CORS for loopback browser development. Reading IDs are URL-encoded by callers. Simulator storage is private, and only the HTTP response is the application input. Simulator state and probe logs are separately reset before each attempt, not between application restarts.

Application must fetch the selected reading from its configured reader URL rather than trust a submitted UID/time/interaction. Unknown reading gives404 `not_found`; connection failure or invalid reader response gives502 `reader_unavailable`, with no database changes. Do not accept request-supplied reader URLs. A reading is processed at most once into a pending scan, as described below; fetching it again is allowed. Tests may inspect actual simulator requests to distinguish protocol use from fabricated state.

### Application HTTP contract

JSON objects use literal text, not HTML. UTF-8 JSON bodies are at most65536 bytes, must be objects and cannot contain non-finite numbers. Invalid/missing field types give400 `invalid_request`. Unknown/inaccessible resources give404 `not_found`; absent/invalid bearer token gives401 `unauthenticated`. Business errors are `{error:{code}}` with statuses defined in the RUs. IDs in paths are URL-encoded. Undocumented HTTP paths give404. Health is public; all other application endpoints except login require authenticated active users.

`User` returned publicly: `{id,username,role,class_ids,student_ids}`. Passwords and password hashes are never returned. Inactive accounts cannot log in. Session tokens contain at least32 random bytes of entropy, stay in browser memory and expire on application restart. Logout invalidates that token only.

`Student`: `{id,name,class_id,presence}`, where presence is `out` initially or `in` after completed check-in. `Guardian`: `{id,name,student_ids,active}`. `Tag`: `{uid,student_id,active}`. `Device`: `{id,name,active}`.

`Scan`: `{id,reading_id,student_id,tag_uid,device_id,direction,at,state,created_by,attendance_id}`. Direction `in|out`; state `pending|completed`; attendance_id is null until completed. `id` is opaque. `Attendance`: `{id,scan_id,student_id,tag_uid,device_id,direction,at,confirmed_by,recipient_id,method}`, method fixed `simulated_tag_tap`, recipient_id null for check-in. `InboxEntry`: `{id,attendance_id,student_id,direction,at,confirmed_by,recipient_id,read}`, with per-user boolean read=false initially. Attendance time is the immutable reading time, not wall clock; no exact generated ID spelling is required.

- `GET /health` →200 `{ok:true}`.
- `POST /api/login` `{username,password}` →200 `{token,user}`, otherwise401.
- `POST /api/logout` `{}` →200 `{ok:true}`.
- `GET /api/me` →200 `{user}`.
- `GET /api/roster` →200 `{students,guardians,tags,devices}`. Scope/order is defined by the public contract above.
- `GET /api/scans` →200 `{scans}` in creation order and viewer scope. Parents get403 `forbidden`.
- `POST /api/scans` `{reading_id,direction}` →201 `{scan,student}` for first valid reading;200 for same reading/same direction replay in scope. Different direction for an existing reading gives409 `reading_conflict`. No attendance or inbox entry is created here. Further behavior is part of the public scan contract.
- `POST /api/scans/{id}/confirm` `{recipient_id}` where null is accepted. →201 `{attendance}` first success,200 on valid replay. Validation, permissions, collection, state/sequence and replay rules are clarifiable with the client.
- `GET /api/attendance` →200 `{attendance}` in completion order, scoped as roster.
- `GET /api/inbox` →200 `{entries}` in completion order. Only parents may use inbox endpoints, otherwise403 `forbidden`.
- `PUT /api/inbox/{id}` `{read:boolean}` →200 `{entry}`. Entries belong to the authenticated parent only, others404.
- `PATCH /api/tags/{uid}` `{active:boolean}` →200 `{tag}`. Only administrators may update. Authorization is checked before target lookup; current state can be set idempotently. Unknown tag404. Changes are durable. No other tag fields can change.
- `PATCH /api/guardians/{id}` `{active:boolean}` →200 `{guardian}`, same administrator-only and durability rules. No other guardian fields can change.

Authentication precedes route business work; forbidden role checks precede resource lookup where stated. Syntax validation occurs after authentication. For a valid scan request, resolve reading, then direction replay/conflict if existing/in scope; otherwise validate active device, active tag, student scope and deliberate tap. Detailed confirmation priority is clarifiable with the client. Invalid requests never consume reading IDs or change durable state. Partial failure must not create a completed scan without its required attendance/inbox state.

### Public browser interface and hooks

`/` serves the actual working UI, including mobile390×844 and desktop1280×900 layouts without horizontal overflow. All fixture names are rendered literally. Export `AttendanceClient` and `AttendanceView` on `window`. Construct client with `(baseURL = '', readerURL = 'http://127.0.0.1:8081')`, view with `(client, document)`. Constructor must not require private internals. Public methods may resolve without payload or reject after updating public error state. `dispose()` tears down owned listeners/resources.

Client methods: `login(username,password)`, `logout()`, `refresh()`, `scan(readingId,direction)`, `confirm(scanId,recipientId=null)`, `setTagActive(uid,active)`, `setGuardianActive(id,active)`, `setRead(entryId,read)`, `dispose()`. Public observables: `user` nullable, `students`, `guardians`, `tags`, `devices`, `scans`, `attendance`, `inbox` arrays, `error` nullable `{code}`. `refresh` requests only endpoints the current role can use. Login/refresh/logout and mutations produce observable current state. A current-session401 clears all private client state; old session responses, including401, cannot overwrite a newer session. Cancellation of obsolete requests is allowed. No tokens/private records survive reload or logout in browser storage.

DOM IDs: `login-form`, `username`, `password`, `login`, `logout`, `error`, `workspace`, `roster`, `scan-panel`, `tag-uid`, `device-id`, `interaction`, `reading-time`, `direction`, `scan`, `pending-list`, `attendance-list`, `inbox`, `tag-list`, `guardian-list`. Inputs: tag UID and integer reading time; selects device ID, `tap|proximity` and `in|out`. Explicit Scan click creates a simulator reading with these values, then submits its returned reading ID to the application. Changing a field alone does not submit or confirm. Role UI hides unavailable actions; backend still enforces authorization.

Roster row `[data-student-id]` displays literal name and current presence; attendance row `[data-attendance-id]`; each pending scan row `[data-scan-id]` contains recipient select `[data-recipient]` (empty choice represents null) and separate confirmation button `[data-confirm]`. Scan rows show student name and direction; only pending scans appear in `pending-list`. Recipient options come from in-scope guardians, without implying that arbitrary selection is authorized. Inbox row `[data-entry-id]` shows student name/direction and a checkbox `[data-read]`, whose actual checked state represents read. Tag management uses `[data-tag-uid]` row with checkbox `[data-tag-active]`; guardian management uses `[data-guardian-id]` row with `[data-guardian-active]` checkbox. Administrative lists only shown to administrators. UI handlers must await/reconcile current state after mutations; no optimistic success may remain after server rejection. Error content must include the returned error code, with freedom for explanatory prose. Dynamic text structure/wording and internal HTML elements are otherwise unconstrained; public hooks locate rendered actions, not the reference DOM structure.


## Visible regression requirements

## RU-001 — Authenticated roster and durable records (visible)

Provide real account sessions and correct initial roster/attendance isolation. Active administrators see all students, teachers see only students whose class is in their class_ids, parents see only their student_ids. Filter students in fixture order. Teachers/administrators receive guardians linked to at least one visible student, filtered guardian.student_ids to visible students, and only tags for visible students; parents receive empty guardians/tags arrays. Staff receive all devices in fixture order; parents receive no devices. Students never authenticate. Attendance reads share student scope and return actual durable completions in completion order. Changes to tag/guardian activity are visible after refresh and survive restart. Only active administrators can change these activity flags. Empty scope is valid and reveals no other records. Private credentials/session tokens are excluded from ordinary response objects, page text and persisted browser storage. Logout/401/late-response behavior follows public contract.

This is existing baseline functionality and a regression obligation, including actual authenticated role-specific browser rendering. It does not require implementing any hidden confirmation policy to pass.

## RU-002 — Deliberate simulated reading and pending preview (visible)

Only teachers/administrators may create/read scans; parents403 `forbidden`. New scan must actually retrieve a reading from the configured prepared HTTP reader. Unknown/inactive devices give422 `inactive_device`; unknown/inactive tags give422 `inactive_tag`; a mapped student outside staff scope gives404 `not_found`. Non-tap interaction gives422 `intentional_tap_required`. Error priority follows the public contract. A valid tap creates one pending scan with exact immutable reading metadata and mapped student, never a completed attendance or inbox message. Direction is explicitly supplied, never inferred from proximity or current presence. The existing reading/same direction replay returns its existing scan and current student at200, retaining original creator; a different direction conflicts409. Both replay and first creation require current viewer scope. Repeated/concurrent requests must create at most one scan per reading. Different reading IDs may create separate pending scans for the same student, including identical timestamps; confirmation sequence is a separate policy.

Teachers see pending/completed scans for their classes, administrators see all; scan list order is creation order. Restart preserves scans and reading replay mapping. The real UI shows a pending preview after a deliberate Scan click and requires a separate Confirm action. Merely scanning, selecting recipient or changing direction never confirms. The starter provides this full baseline.


## Development work

Complete confirmation and parent-inbox behavior after clarifying operator authorization, collection membership, attendance sequence/replay and notification isolation with the simulated client. The supplied project contains real baseline workflows. Only the prepared simulator protocol is in scope.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
