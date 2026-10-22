Internal role note: the operation adapters and regression suites under /public_tests are evaluator-only, not freelancer development commands. Do not disclose their source or advise the freelancer to run them. For a requested local check, explain the relevant application interface and use independently written Python calls to the agreed component interface.

# Offline field-work storage and synchronization

Complete the supplied Python project through `process_field_action(state, action, store=None, transport=None)`. Existing authentication, connection, queue and status handling is provided. Add persistence through OfflineStore(root, key) and delivery through SyncTransport(endpoint). All fixtures and credentials are generated locally; no customer job bundle is included.

The entry point returns the full next state at top level and the current summary under result without mutating input dictionaries. Authentication is a synthetic test fixture using the disclosed password digest, two-factor age and session-time rules. It is not a production identity service or an endorsement of fast unsalted hashes for deployed passwords. Key provisioning belongs to the caller; keep encryption keys outside returned state. The store root and sync endpoint are configured for isolated evaluation.

This is a reconstructed Python storage/sync component, not the original mobile app. Operating-system keychain, background scheduling, device management and live email/cloud providers are outside the selected scope. Further storage and synchronization requirements can be clarified.

Action-result interface: successful authentication returns `result.two_factor_used` as a boolean describing whether this authentication used the two-factor code. Rejected operations return `error: {code: string}` in the chainable state. Authentication failure uses `auth_denied`; an absent or expired required session uses `session_expired`. These names describe the existing authentication interface; ask the client for the exact age/session boundaries and storage/synchronization policies.

## Prepared execution interface

The benchmark supplies the reusable `python-crypto` environment with Python, cryptography 50.0.1, cffi 2.1.1 and pycparser 3.0 already installed. Do not run pip or fetch dependencies during the task. Work in `/workspace`; generated files belong in `runtime/`.

Run visible checks with `python /public_tests/test_public.py`. The public driver `python -I /public_tests/component_runner.py` reads one JSON object per input line and writes one JSON response. Use fields `state` and `action` for normal operations, optional `store: {"root": "...", "key_hex": "..."}` for a caller-provided 32-byte key and storage directory, and optional `endpoint` for the prepared local HTTP receiver. Keys are driver configuration and must not be copied into business state. Responses contain `ok`, `result`, and `inputs_unchanged`, or an exception report.

The same driver supports `operation: "write_bundle"` with `user_id`, `job_id`, and `data`, or `operation: "read_bundle"` with `user_id` and `job_id`, for direct store checks. These call the public store interface; filenames and internal helper functions are unrestricted. The evaluator separately observes file contents and HTTP effects, so a successful response alone does not establish correct storage or delivery.

Before the budget, the manager creates `runtime/store.json` (synthetic key and store root), `runtime/example.jsonl`, and a local acknowledgement endpoint at `http://127.0.0.1:38930/apply`. Run `python -I /public_tests/component_runner.py < runtime/example.jsonl` for the prepared authentication example. The acknowledgement service accepts intents only; it does not send email or upload to a real cloud.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
