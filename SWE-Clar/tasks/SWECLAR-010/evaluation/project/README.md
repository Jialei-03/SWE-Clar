# Competitor page monitor

Extend a running, independently constructed competitor-monitoring web application. Account sign-in and a saved competitor directory already work. Complete actual page snapshots, change history, archive/restore and provider-backed subscriptions. Ask the synthetic client to clarify those workflows' decisions. All accounts, pages and receipts are synthetic local material.

## Prepared execution

Work in `/workspace`. Python 3.12, SQLite 3.45, Chromium 140 and Playwright 1.55 are already installed. The benchmark prepares and health-checks the page/receipt provider before the task begins. External networking is disabled; loopback HTTP is available. Limits are 2 CPUs, 2 GiB RAM, 256 processes, 512 MiB workspace and 1 GiB temporary storage. No installation or external account is required.

- Start the app: `python server.py --port 8000 --db monitor.sqlite --fixtures fixtures/demo.json`.
- Open `http://127.0.0.1:8000/` in the prepared browser.
- Public checks: `python /public_tests/test_public.py`.
- Stop with Ctrl-C. Restart on the same database to retain state; choose a new database filename for a fresh demo.
- `--port 0` selects a free port; startup prints a JSON object with numeric `port`. Errors go to stderr; use ordinary shell redirection to retain logs.
- Provider URL defaults to `http://127.0.0.1:38920`, overridable with `--provider-url URL` for the benchmark's independent service instances. Read health at `/health`. The provider is already running, independently of your app.

The starter includes a real SQLite-backed HTTP server and `web/` browser frontend. Preserve commands, public schemas, named business database columns and control IDs; internal architecture and styling are free. Hidden checks and reference implementations are not application resources. Do not edit `/opt/sweclar` or `/public_tests`.

## Provider protocol and demo

GET `/pages/<slug>` returns synthetic static HTML. A slug matches `[A-Za-z0-9_-]{1,64}`. Query strings are accepted and ignored by this provider. GET `/v1/receipts/<receipt_id>` returns `{id,account_id,sequence,plan,status}`, or a 404 JSON error for a missing receipt. Sequence is integer 1..2147483647, plan is `full` or `basic`, status is `active`, `cancelled` or `payment_failed`. Provider errors use actual HTTP statuses. The app must request these actual resources; receipt properties are provider authority, not form fields. The client can clarify validation, billing ordering and access decisions.

The prepared demo has pages `demo-page-a` and `demo-page-b`, accounts `account-a` and `account-b` with password `local-demo`, and receipts `demo-full-a` (sequence 1, full/active for account-a), `demo-cancel-a` (2, full/cancelled), `demo-renew-a` (3, full/active), and `demo-full-b` (1, full/active for account-b). These IDs are illustrative; never hard-code them into business logic.

For local development only, POST provider `/demo/page` with `{slug,html}` replaces a demo page; POST `/demo/reset` with `{}` resets demo pages and receipts. These endpoints intentionally have no secrets and alter only the disposable demo provider. Public tests use separate generated application IDs so existing app data need not be discarded. Hidden evaluation starts a fresh provider using the same read protocol and dependency image; its owner controls fixtures privately and the `/demo/*` endpoints return 403. Candidate code must never call control endpoints in its normal workflow.

## Foundation and data contracts

Fixture JSON has `accounts`, `competitors`, `subscriptions`. Accounts use `{id,name,password}`. Competitors use `{account_id,competitor_id,name,archived,urls:[url,...]}` with fixture URLs resolved against the configured provider if they start with `/pages/`. Subscriptions use `{account_id,sequence,plan,status}`; initial sequence may be 0. Fixtures use valid unique references, at most 20 accounts, 100 competitors and ten URLs per competitor. Demo business content is literal text and can contain markup-looking characters. Fixture initialization runs only for a fresh database.

IDs match `[A-Za-z0-9_-]{1,64}`. Names are trimmed nonempty Unicode text, at most 120 characters. Runtime timestamps are integer Unix milliseconds in `[0,253402300799999]`, excluding booleans. JSON flags must be booleans. Requests use exactly the documented fields, with no duplicate JSON keys or repeated query parameters. Bodies are JSON objects up to 32768 UTF-8 bytes. All API endpoints except login require `Authorization: Bearer TOKEN`. Credentials are checked server-side and sessions are opaque. Return 401 for invalid sessions/credentials, 400 for malformed input and 404 for missing or foreign resources. Error bodies contain `{"error":{"code":"..."}}`; wording is free. Other workflow statuses/decisions are clarifiable. Success may contain harmless additional metadata, never passwords or session lists.

Create an own uniquely identified competitor with one through ten distinct normalized page URLs. Only the exact configured HTTP provider origin and `/pages/<slug>` paths are accepted. Reject userinfo, whitespace, bad ports, percent-encoded path components, foreign origins and other protocols. Normalize host/scheme case, remove fragment, preserve path/query bytes; input URL length is at most 2048. URL IDs are generated stable identifiers scoped to each account. Duplicate competitor ID is 409 and duplicate URLs are 400. A page may be independently tracked under different competitors/accounts. Foundation listing filters `status=active|archive|all` (default active) and optional casefolded name substring `q`; sort by name.casefold() then competitor_id. URL order is creation order. Name editing and URL removal are outside this task. Preserve existing fixture state and owner isolation.

Required SQLite business tables/columns (extra tables/columns permitted):

- `accounts(id,name,password)`; `sessions(token,account_id)`; `meta(key,value)`.
- `competitors(account_id,competitor_id,name,archived)`; archived is 0/1.
- `urls(account_id,url_id,competitor_id,ordinal,url,text,sha256,observed_at_ms)`; final three fields nullable before observation.
- `snapshots(account_id,snapshot_id,url_id,observed_at_ms,text,sha256)`.
- `events(account_id,snapshot_id,url_id,observed_at_ms,before_text,after_text,before_sha256,after_sha256)`.
- `subscriptions(account_id,sequence,plan,status)`; `receipts(account_id,id,sequence,plan,status)`.

## Application HTTP interface

| Method and path | Input | Successful JSON or bytes |
|---|---|---|
| GET /health | none | `{ok:true}` |
| POST /api/login | `{id,password}` | `{token,account:{id,name}}` |
| POST /api/logout | `{}` | `{ok:true}` |
| GET /api/me | none | `{account:{id,name}}` |
| GET /api/competitors | optional query `status,q` | `{competitors:[{competitor_id,name,archived}]}` |
| POST /api/competitors | `{competitor_id,name,urls:[url,...]}` | `{competitor:{competitor_id,name,archived}}` |
| GET /api/competitor | query `competitor_id` | `{competitor:{...},urls:[{url_id,url,text,sha256,observed_at_ms}]}` |
| POST /api/archive | `{competitor_id,archived}` | `{competitor:{...}}` |
| POST /api/snapshots | `{snapshot_id,url_id,observed_at_ms}` | `{snapshot:{snapshot_id,url_id,observed_at_ms,text,sha256},duplicate:boolean}` |
| GET /api/history | query `url_id` | `{events:[{snapshot_id,url_id,observed_at_ms,before_text,after_text,before_sha256,after_sha256}]}` |
| GET /api/history.csv | query `url_id` | actual UTF-8 CSV attachment, filename `changes.csv` |
| GET /api/subscription | none | `{subscription:{sequence,plan,status},writable:boolean}` |
| POST /api/subscription | `{receipt_id}` | `{subscription:{sequence,plan,status},writable:boolean,duplicate:boolean}` |

## Browser interface

Keep these IDs on the corresponding functional controls. Controls must be usable by a real browser. Rows expose `data-competitor-id` or `data-url-id` and a `data-action=select` button. Freeform markup/style changes are allowed; scrolling is allowed. Render all account/competitor/page strings literally. Show pending/error/empty states and keep context consistent when requests finish after selection or account changes.

| IDs | Behavior |
|---|---|
| login-form, account, password, login-status | sign-in form and feedback |
| application, identity, logout, refresh, status | signed-in workspace and refresh |
| competitor-form, competitor-id, competitor-name, competitor-urls, competitor-save, create-status | create; URLs textarea has one URL per line |
| filter-form, filter-q, filter-status, filter, competitors | directory filtering and selectable rows |
| competitor-detail, urls, url-detail | selected competitor/URL and current text/hash |
| archive, restore, archive-status | selected competitor lifecycle |
| snapshot-form, snapshot-id, snapshot-time, snapshot-save, snapshot-status | actual snapshot; time is an ISO UTC string with Z suffix, converted to milliseconds |
| history, history-download | before/after events and actual CSV download for selected URL |
| subscription-summary, subscription-form, receipt-id, receipt-submit, subscription-status | current provider-backed subscription and receipt submission |

Initial task information establishes the project, schemas and directory rules. Ask the client about normalization/change decisions, replay/error behavior, archival boundaries and subscription access/order. Implement them consistently in HTTP, persistent state and browser workflows.
For new snapshots, nonwritable subscription access takes priority over the archived-state check: both conditions together return 403 with no fetch or mutation. Authorized archived-only requests return 409. Exact successful snapshot replays remain reads; invalidation during an in-flight snapshot still returns 409.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
