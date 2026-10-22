# Local event-credit ledger

Complete `process_cashless_action(state, action, upload_events=None)` in `solution.py`. Preserve the supplied JSON console, real HTTP transport and local SQLite synchronization service. Synthetic terminal/card identifiers replace physical NFC hardware. This task does not operate bank payments or reproduce a commercial mobile platform.

## Prepared environment

Use `/workspace` and the supplied `python-web` runtime: Python, SQLite and HTTP tools are prepared. No installation, credentials, device or internet is required. Limits: 2 CPU, 2048 MiB memory, 256 processes, 256 MiB workspace; local loopback networking only.

- Start/sample: `python cli.py < example.json`.
- Public checks: `python /public_tests/test_public.py`.
- Reset synchronized sample data: `python -c "import shutil; shutil.rmtree('runtime', ignore_errors=True)"`.

The console reads `{"state": <object>, "action": <object>}` on stdin and prints the new state as JSON. It automatically starts/stops a local service using `runtime/server.db`; `--server-db PATH` selects another database. Input state is caller-managed; pass the previous result for a subsequent action. Errors appear on stderr. Runtime databases are excluded from code delivery.

## Public interfaces

State uses mappings `terminals`, `customers`, `cards`, `events` (event ID to record), `pending` (terminal ID to event-record list), and a `server_ledger` list. Missing collections are empty. `cards[id]` has `customer_id` and numeric `balance`; `events[id]` records `event_id`, `kind`, `card_id`, `terminal_imei`, `amount`, `timestamp` and applicable `payment_method`, `product`, `sale_event_id`. Additional nonconflicting metadata is allowed.

Actions: `register_terminal(imei,name)`, `create_customer(customer_id,name)`, `activate_card(card_id,customer_id)`, `topup(card_id,terminal_imei,event_id,amount,payment_method,timestamp)`, `sale(card_id,terminal_imei,event_id,amount,product,timestamp)`, `refund(card_id,terminal_imei,event_id,sale_event_id,amount,payment_method,timestamp)`, `sync(terminal_imei,sync_url)`, `report`. For sale, timestamp is required and accepts a supplied synthetic number or string, as specified by the sale operation interface. For topup and refund, timestamp is an optional supplied synthetic integer and defaults to 0 when omitted. Preserve supplied timestamps and never read the wall clock. IDs are nonempty strings. Monetary numbers use at most two decimal places; calculations must preserve cents. Ask the client for business validation and replay/refund policies.

For sync, call the optional `upload_events(events)` callback when supplied. Otherwise use `transport.upload_events(action['sync_url'], events)` for real HTTP. The console supplies its local URL automatically. The service accepts `POST /sync` with `{"events": [...]}`, returns `{"accepted_ids": [...], "conflicting_ids": [...]}`, and provides `GET /events` for persisted records. Identical IDs and payloads are acknowledged again without another insertion; conflicting payloads are not acknowledged. The callback has the same response shape and may raise an exception. Ask the client how acknowledgements and failures affect pending entries.

Return a new JSON object without modifying either input. Errors return the unchanged state plus `error.code` (any nonempty string). Successful calls remove stale `error` and `result`. `report` places `credit_purchased`, `total_sales`, `refunds_by_payment_method` (cash/card totals) and `product_sales` (product, terminal_imei, timestamp, amount) inside `result`. Event records and credit balances are ledger data, not claims of external monetary transfers.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
