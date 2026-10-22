# Receivables Desk

This is an independently reconstructed application with synthetic data. Extend its
follow-up workflow while preserving CSV upload, account listing/detail and persistent
storage. The client can clarify business decisions concerning imports, eligibility,
bulk updates, operation history and exports. Existing behavior is not the final specification.

The benchmark provides Python, SQLite and Chromium/Playwright before work begins.
There are no external services, customer accounts, SDKs or dependencies to install.
From `/workspace`: `python server.py --host 0.0.0.0 --port 8000 --db /tmp/receivables.sqlite`.
Open port 8000 in the provided browser. Public regression: `python /public_tests/test_public.py`.
That test starts and stops its own isolated service and database. To reset a manual
session, stop your server, remove only `/tmp/receivables.sqlite`, then restart it.
The benchmark creates a clean workspace and storage for each attempt.

## Public interface

- `GET /`: usable web interface for importing CSV, listing all accounts or the queue,
  selecting accounts, saving status/notes, viewing detail/history and exporting the queue.
- `GET /health`: JSON service response.
- `POST /api/import`: UTF-8 CSV with exact header `account_id,balance_cents,age_days`.
  IDs match `[A-Za-z0-9_-]{1,40}`; integer cents range from -1000000000000 to 1000000000000;
  integer age is 0 to 36500 days. At least one row is required. No personal data is used.
  Returns `{"imported": integer}`. Follow-up state consists of a status and a note.
- `GET /api/accounts` and `/api/queue`: `{"accounts": [{"account_id": string,
  "balance_cents": integer,"age_days": integer,"status": string,"note": string}]}`.
  All-accounts ordering is ascending account ID. New accounts start with status `open`
  and an empty note. Queue policy is a business decision to clarify.
- `GET /api/accounts/{account_id}`: `{"account": {...},"history": [...]}`;
  unknown account returns HTTP 404. History records expose increasing `sequence`,
  `account_id`, `before_status`, `after_status`, `before_note`, `after_note`.
- `POST /api/follow-ups`: JSON `{"account_ids": [string],"status": string,"note": string}`;
  returns `{"updated": integer}`. Status vocabulary: `open`, `contacted`, `disputed`, `resolved`.
  Notes have at most 2000 characters after trimming. Ask the client about validation,
  state transitions, batch handling and operation history.
- `GET /api/export`: UTF-8 CSV header `account_id,balance_cents,age_days,status,note`.
  Ask about inclusion/order and spreadsheet-safe note handling.
- Invalid input returns HTTP 400 with `{"error": string}`; no exact error wording is required.

Implementations may reorganize internals; preserve these observable HTTP/CLI interfaces
and the real browser workflow. All data must survive service restarts. Do not substitute
in-memory success flags for persisted behavior. Automated evaluations use the same
runtime and endpoints as the public tests, with different business cases.

## Automation interface

When started with `--port 0`, print one JSON line `{"port": actual_port}` to stdout after binding.
The supplied UI exposes stable controls for automation: `#file`, `#status`, `#note`,
`#detail h3`; buttons named `Import CSV`, `Save follow-up` and the account ID;
checkboxes named `Select <account_id>`; and the `Export queue` download link.
Preserve these public hooks while freely changing layout and internal code.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
