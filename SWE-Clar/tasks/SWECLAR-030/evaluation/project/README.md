# Local family policy service

Extend the supplied Python HTTP/SQLite service. Mode configuration and durable storage already work; implement policy setting, access decisions, activity reports and account deletion. Request identities are supplied by a trusted caller. This is a local component with synthetic access events and a local notification queue; it does not intercept device traffic or deliver push notifications.

Run from `/workspace` in the prepared `python-web` environment. The benchmark supplies Python, SQLite and a writable `runtime/` before the coding budget. No installation or external credentials are required.

- Start: `python server.py --db runtime/state.db --seed seed.json --port 8080`
- Public checks: `python /public_tests/test_public.py`
- Reset: stop the server, then `python -c "from pathlib import Path; Path('runtime/state.db').unlink(missing_ok=True)"`, and restart.
- Server logs appear in the starting terminal. Use `http://127.0.0.1:8080/health` for readiness.

`GET /state` is a local development snapshot, not a production user-facing authorization endpoint. `POST /action` takes a JSON object and returns HTTP 200 for a processed action, including business errors. Malformed JSON/non-object/nonfinite input returns HTTP 400 and `error.code=invalid_request`. Actions are below 1 MiB. Successful actions return the full chainable state and optional `result`; errors return `error.code` and commit no state changes. Restarting with the same database preserves successful operations. Database schema and additional metadata fields are implementation choices.

The state contains `users`, `devices`, `policies` objects and `activity`, `notifications`, `audit` arrays. `process_control_action(state, action)` in `policy.py` must not mutate its arguments. Authentication and device telemetry collection are outside the component: supplied actor IDs and minute totals are trusted inputs.

Action shapes (business decisions can be clarified):

| type | Fields | Result / business error codes |
|---|---|---|
| configure_mode | user_id, device_id, mode=self or parent_child; child_id for parent_child | result.device_id / link_denied |
| set_policy | actor_id, device_id, blocked_domains list, blocked_apps list, app_daily_limits object | updated policies / policy_denied, invalid_policy |
| check_access | device_id, event_id, target_type=domain or app, target; optional used_minutes default 0 | result.allowed boolean, result.reason / invalid_access_check, event_conflict |
| report | parent_id, device_id | result.activity array / report_denied |
| delete_account | user_id | updated state / account_missing |

IDs and app names are nonempty strings. Hosts are nonempty ASCII labels separated by dots, containing letters/digits/hyphens; one final dot is accepted. Inputs are hosts, not URLs. Minute values are finite nonnegative numbers, excluding booleans. Policy collections must have the declared types and string keys/items. Unknown action types return `unsupported_action`.

Self mode binds the user's own device. Parent-child mode requires parent/child roles and the child's matching parent_id. Device IDs cannot be reused; a child can own at most one linked device. Cross-family linking is rejected. Device records contain owner_id/mode and, for parent-child mode, parent_id. Existing mode behavior is a regression requirement.

Resources: 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace; network restricted to local loopback. Hidden evaluation uses the same runtime and command interface. You may reorganize code while preserving the public function and service interfaces.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
