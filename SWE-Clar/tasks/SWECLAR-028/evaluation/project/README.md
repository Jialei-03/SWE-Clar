# Shift scheduling automation service

Build a local scheduling automation service using the provided Python and SQLite project. This is an independently reconstructed workflow task; it does not claim n8n import compatibility or use external business accounts.

The benchmark prepares Python, SQLite, timezone data, a writable database, configuration, and a local notification endpoint before the coding budget. Do not install dependencies or request service credentials. Work in `/workspace`; generated data belongs in `runtime/` and is excluded from submission. Start with `python server.py --config runtime/config.json --port 8080`. The configuration supplies `database`, `notification_url`, and an IANA `timezone`.

The existing signup path links employees, shifts and signups, sends employee SMS/email and assigned-manager email, and confirms successful signups. Complete the scheduled automation and preserve the existing service. Ask the client for reminder eligibility, manager reporting, capacity handling and attendance policies.

## HTTP contract

- `GET /health`: HTTP 200 with `{"ready": true}`.
- `GET /state`: HTTP 200 with `employees`, `shifts` and `signups` arrays, reflecting persisted records.
- `POST /signups`: JSON `{"id":"signup-a","shift_id":"shift-a","employee":{"id":"worker-a","name":"Worker A","email":"worker@example.test","phone":"+12025550101"}}`. Return the persisted signup with `id`, `employee_id`, `shift_id`, `status` and `checked_in`.
- `POST /tick`: JSON `{"now":"2030-04-03T06:00:00+00:00"}`. The benchmark's scheduler invokes this with an explicit clock. Return HTTP 200 after successful processing. Do not rely on the host's actual date.

Employee identity is resolved by email. An existing employee is reused. Shifts supply `id`, `starts_at` (offset-aware ISO timestamp), `location`, `address`, `map_url`, `manager_email`, `capacity` and `status`. Signup IDs identify one employee/shift pair; conflicting reuse must fail. Same-ID repeated requests must not duplicate records or successful notifications. Use SQLite for persistent records; internal tables and implementation may differ if the supplied seed data remains usable and `/state` preserves these fields.

The notification endpoint accepts `POST /messages` with string fields `id`, `channel`, `recipient`, `body`. Channels are `sms`, `email`, `manager_email`. A successful request returns 200. A stable unique ID makes retries idempotent: the same payload returns 200 again, but changed payload under the same ID returns 409. Transient errors may return 503. Do not mark a notification-dependent step complete after failure. The service has no public receipt-editing endpoint.

Signup notification bodies must contain the worker, shift timestamp, location, address and map URL. Wording and internal helper names are unrestricted. Return 400 for malformed input or conflicting records and 503 for unavailable delivery; unknown paths return 404. No public internet or real delivery is needed.

## Structured notification interface

For machine-readable roster notifications, `body` is a JSON array of records with `shift_id`, `starts_at`, `location`, `total`, `filled`, and `remaining`. Full-capacity notices use one JSON record with the same fields. Array order, whitespace and JSON key order are unrestricted. These serialization choices are benchmark transport conventions, not original customer wording. Other notification bodies remain ordinary text. Ask the client when and to whom these reports should be sent.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
