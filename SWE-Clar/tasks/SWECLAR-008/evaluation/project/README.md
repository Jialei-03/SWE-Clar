# Household monitoring application

Extend this independently authored local application while preserving its working login, household access, sensor ingestion and current room view. Complete the room-rule editor, duration/window-based activity alerts and rolling CSV report after clarifying their exact policies. All households, users, sensor events and room layouts are synthetic. No original customer code, account, device configuration, floorplan or attachment is included.

## Prepared environment and commands

The benchmark supplies Python 3.12, SQLite 3.45 and Chromium 140 with Playwright 1.55. The application uses the Python standard library and local HTML/CSS/JavaScript; no dependency installation, cloud account, real device or remote service is needed. Work in `/workspace` with 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace and 1 GiB temporary storage. External networking is disabled; loopback HTTP is available. SDKs, browser files and public checks are protected.

- Start the app: `python server.py --port 8000 --db monitoring.sqlite --fixtures fixtures/demo.json`.
- Run visible regression checks: `python /public_tests/test_public.py`.
- Open `http://127.0.0.1:8000/` using the prepared browser, or use Playwright from a Python script. The server prints one JSON object containing its actual `port` on startup; `--port 0` asks the OS for a free port.
- Stop the development server with Ctrl-C; restart with the same database path to retain data.
- To start a fresh demo, stop the server and choose a new database path. Fixtures initialize only a new database and must not overwrite existing data on restart.

The protected environment preflight runs before candidate work. The application server and its database are the project being maintained; starting and testing them is ordinary development. The ingestion endpoint represents a local synthetic sensor feed, not compatibility with a proprietary device or a production monitoring service.

Public demo accounts are `resident-a` / `demo-resident`, `resident-b` / `demo-resident` and `caregiver` / `demo-caregiver`. The separate example feed token is `synthetic-local-feed`. These are artificial local credentials supplied for development. Evaluation fixtures vary every account, household, sensor and token; do not hard-code the example identities.

## Project and persistent inputs

`server.py` provides the HTTP application, `storage.py` initializes and opens the SQLite store, `monitoring.py` supplies access/snapshot/rule/report logic, and `web/` contains the actual browser application. Keep the documented server command and HTTP contract. Internal implementation and database queries are free; the named tables below are public persistence interfaces used to check actual stored data.

The fixture JSON contains:

- `clock_ms`: the demo evaluation time. Queries use explicit `as_of`, not the computer's clock.
- `feed_token`: the separate ingestion authority.
- `users`: `{id,name,role,password,household_id,assignments}`; roles are `individual` and `caregiver`.
- `households`: `{id,name,freshness_minutes,night_start,night_end,sleep_start,sleep_end}`. Window endpoints are integer UTC minutes from 0 through 1439; precise window behavior is clarifiable.
- `rooms`: `{household_id,id,name}`.
- `sensors`: `{household_id,id,room_id,name,kind}`. Boolean `contact` and `presence` sensors are supplied.
- `events`: `{household_id,event_id,sensor_id,timestamp_ms,value}`.
- `rules`: `{household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity}`.

Identifiers match `[A-Za-z0-9_-]{1,64}`. Observation timestamps and `as_of` are integer Unix milliseconds in `[0,253402300799999]`; booleans are not timestamps. Room and sensor identifiers can repeat across households. Fixtures provide valid references, labels and household configuration, at most 10 households, 100 rooms and 5,000 observations. HTTP requests may deliberately contain invalid data to exercise rejection. Names are literal Unicode text, including markup-like characters.

SQLite retains `users`, `assignments`, `sessions`, `households`, `rooms`, `sensors`, `events`, `rules` and `meta`. Their initial schema is in `storage.py`; preserve documented business columns and values, allowing harmless additional columns/tables. Store event values as SQLite 0/1 and expose actual JSON booleans. Store `rules.enabled` as 0/1 and expose a JSON boolean. Configuration and observations must survive a real server restart. Login responses and data endpoints must not expose passwords, password hashes, the feed token or another user's session token.

## HTTP contract

JSON responses use `Content-Type: application/json`; failures contain `{"error":{"code":"..."}}`. Clients must observe HTTP status, not a success flag inside an error. Authenticate user requests with `Authorization: Bearer TOKEN` from login. Ingestion uses the separate configured feed token instead.

| Method and path | Input | Successful output |
|---|---|---|
| `GET /health` | None | `{"ok":true}` |
| `POST /api/login` | `{id,password}` | `{token,user:{id,name,role}}` |
| `POST /api/logout` | `{}` with session | `{ok:true}`; revoke that session |
| `GET /api/me` | Session | `{user:{id,name,role}}` for current actor |
| `GET /api/homes` | Session | `{households:[...],clock_ms}` for accessible households only |
| `POST /api/ingest` | Event object, feed bearer token | `{accepted:true,duplicate:boolean}` |
| `GET /api/snapshot` | `household_id` and `as_of` query fields | `{as_of,rooms:[...]}` |
| `GET /api/rules` | `household_id` and `room_id` query fields | `{rules:[...]}` |
| `PUT /api/rules` | One complete rule object | `{rule:{...}}` |
| `GET /api/alerts` | `household_id` and `as_of` query fields | `{as_of,alerts:[...]}` |
| `GET /api/report` | `household_id` and `as_of` query fields | `{as_of,window_start,rooms:[...]}` |
| `GET /api/report.csv` | Same authorized report query | CSV download named `activity-report.csv` |

Use exact required request fields and one value per declared query field. Invalid user credentials/sessions or feed authority return 401. An unauthorized household request returns 403 without leaking its contents. Valid feed authority with an unknown sensor/household pair returns 404; malformed input returns 400. Replaying the same event ID within one household with identical sensor, timestamp and value succeeds without another row; conflicting reuse returns 409 without changing the earlier event. The same event ID in a different household is independent. Concurrent duplicate ingestion must remain atomic. Out-of-order and future observations can be ingested.

A snapshot room row is `{household_id,room_id,name,sensors}`. Each sensor is `{sensor_id,name,kind,value,timestamp_ms,stale}`. Include every configured room/sensor. Use the last observation at or before `as_of`, choosing the greatest event ID for a timestamp tie. No matching observation produces null value/timestamp and `stale:true`. Otherwise staleness is a strict age comparison to `freshness_minutes`; equality is fresh. Sort room and sensor IDs. Reading must not alter events or configuration.

Rule input kinds are `fridge_open`, `bathroom_occupied_day`, `bathroom_occupied_night`, `no_occupancy` and `exterior_open_night`; severity tokens are `info`, `warning` and `critical`. The editor uses a boolean enabled flag and numeric minute threshold. Editing authority, valid threshold boundaries, compatible sensors and saved-rule semantics are available through clarification.

Each alert exposes `household_id,room_id,kind,sensor_id,start_ms,trigger_ms,severity,alert_id,explanation`. Each report room exposes `household_id,room_id,event_count,sleep_event_count,alert_count`. CSV has exactly that five-column report-row header, followed by corresponding numeric rows. The rule, time-window, duplicate/interval and report-count semantics are available through clarification. Harmless extra fields in returned JSON objects are permitted unless they expose protected data. No specific alert ID encoding or explanatory sentence is required; identities must be stable under the clarified policy.

## Real browser interface

Keep these DOM IDs on the corresponding controls/content so public and private tools can exercise the application. Internal DOM structure and styling are free; fixture and explanation text must remain literal text.

| IDs | Purpose |
|---|---|
| `login-form`, `account`, `password`, `login-status` | Login and visible result |
| `application`, `identity`, `logout` | Authenticated application, actor and logout |
| `household`, `as-of`, `refresh`, `status` | Authorized selection, ISO UTC evaluation-time input, refresh and visible result |
| `rooms` | Actual room zones/cards with `data-room-id` |
| `data-sensor-id` on each sensor element | Sensor ID/name, current state, timestamp and freshness; identify its visible state text with class `state`, using On, Off or Unknown (case-insensitive) |
| `alerts` | Actual current alert entries with `data-alert-id` |
| `rule-room`, `rule-kind`, `rule-sensor`, `rule-threshold`, `rule-severity`, `rule-enabled` | Rule editing controls |
| `rule-form`, `save-rule`, `saved-rules`, `rule-status` | Actual save, saved values and success/failure feedback |
| `download`, `download-status` | Actual CSV download and failure feedback |

Poll the entered evaluation time at least once every two seconds and allow manual refresh. Ingestion at or before that time must update the existing page without a reload. Discard responses from a previous account, household or evaluation time. Login/logout clears old page data. Keep controls and lists usable at 390x844 and 1280x900 without horizontal overflow or script errors. Show empty and failed states distinctly and allow retries. A visual room card is acceptable; no customer floorplan is needed. The private reference implementation and hidden assertions are not application resources.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
