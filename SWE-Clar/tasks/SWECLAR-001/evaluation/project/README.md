# Property workspace

Complete this independently authored local listing application. It already has HTTP routes, a browser interface, SQLite storage, draft validation and factual description templates. Comparable pricing, offer synchronization, access policy and offer review are unfinished. Ask the client about those business decisions. All users, properties and offers are synthetic.

## Prepared environment

The benchmark provides Python 3.12, SQLite, Chromium/Playwright and a live synthetic offer service. No installation, account, internet access or customer files are needed. Run from `/workspace`:

```sh
python server.py --port 8080 --db /tmp/property-workspace.sqlite
python -I /public_tests/test_public.py
```

`OFFER_SERVICE_URL` points to the already-running service. You can select a separate prepared test fixture with `--offer-service URL` and `--seed FILE`; tests provide these. Start a fresh database for a fresh local trial. The process prints one JSON line containing its actual `port`, including when using `--port 0`. The seed is used only for an empty database. `/health` confirms application readiness.

Resource limits: 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace, 1 GiB temporary storage and 256 MiB shared memory. Writable storage consumes the same memory budget. System tools, public tests and provider implementation are read-only. Individual commands have a 120-second limit. Browser tests use the supplied browser; they do not need a desktop GUI.

## Public interface

`GET /api/actors` exposes the synthetic fixture identities. Requests to listing/analysis/review APIs supply `X-Actor` with a fixture ID; this represents an already-authenticated upstream identity. Do not build a password or registration system. The caller cannot provide a role or change ownership. Ask the client which operations and records each role can access.

Editable fields are `label` (trimmed nonempty string, at most 120 characters), `property_type` (`house` or `apartment`), `bedrooms` (integer 0..10), `bathrooms` (integer 1..10), `floor_area` (integer 10..2000), `asking_price` (integer 1..10^12) and `features` (at most 20 nonempty strings, each at most 80 trimmed characters). Booleans do not count as integers. Features are trimmed and deduplicated in first-occurrence order. Features default to an empty list on creation; omitted fields remain unchanged on an update. Other required fields must exist in the resulting record. Unknown or immutable submitted fields are errors. Invalid creation/update rejects the whole operation.

Stored records also contain generated `id`, fixture-linked `owner_id`/`agent_id` and `state`. New records use the caller's identity and its fixture-assigned agent; records always remain `draft`. No publication endpoint is provided.

- `GET /api/listings` → `{"listings": [...]}` sorted by ID.
- `GET /api/listings/<id>` → `{"listing": {...}, "offers": [...], "notifications": [...]}`.
- `POST /api/listings` creates an editable draft; `PUT /api/listings/<id>` updates supplied fields. Both return `{"listing": {...}}`.
- `POST /api/listings/<id>/analysis` takes `{"comparables": [...], "count": 2|3, "tone": "warm"|"concise"}` and returns `{"pricing": object|null, "descriptions": [string]}`. At most 1000 comparables are accepted. Each comparable has `id` (nonempty string, at most 64 characters), `property_type`, `bedrooms`, `floor_area`, `sale_price` (integer 1..10^12) and `age_days` (integer 0..36500); other scalar domains match the listing. Invalid comparable records are ignored. Ask about selection, duplicate IDs, limits, ordering, adjustment, aggregation, rounding and confidence. Pricing, when available, has integer `minimum`, `midpoint`, `maximum`, numeric `confidence`, `comparable_ids` and `adjusted_prices` in matching order.
- Descriptions must provide exactly `count` different readable strings in stable order, each including the label, property type, bedrooms, bathrooms, area, asking price and selected tone. Include the supplied features and do not invent property facts. Templates are acceptable; no remote language model is required. Equivalent prose is allowed.
- `POST /api/sync` takes `{"now": integer}` and returns `{"mode": string, "updated": integer, "polled": boolean}`. `now` is a controlled nonnegative clock in seconds, at most 10^12. The manager drives ticks; do not create a scheduler or wait real minutes. Ask about transport choice, timing, persistence, retries and event processing.
- `POST /api/offer-events` takes `{"events": [...]}` and returns `{"updated": integer}`. This and sync are simulation-service endpoints, separate from user identity routing. Do not infer user roles from event payloads.
- `POST /api/offers/<id>/review` takes `{}` and returns `{"url": string}`. Ask about permitted effects and repeated requests.

A notice contains increasing integer `sequence`, `kind`, `actor`, `offer_id`, `revision`, `listing_id` and `data` (`amount`, `terms`). Successful operations return 200, creation 201; validation failures return 400 with `errors` object. Unknown identity is 401; unavailable single records are 404; known read-only access is 403; provider failure is 502. Unfinished starter features currently return 501. No rejected operation may partially change application data.

## Synthetic offer provider

The inspectable `/opt/sweclar/offer_service.py` defines a real loopback HTTP service. Each test creates separate provider state. There is no external platform or commercial account.

- `GET /health` → `{"ready": true}`.
- `GET /capabilities` → `{"webhook_supported": boolean}`.
- `POST /subscriptions` takes `{"callback_url": "http://127.0.0.1:PORT/PATH"}`. This single-consumer fixture replaces its callback URL and returns `{"subscribed": true}`; unsupported webhook mode returns 409. Rebinding after application restart is supported.
- `GET /offers?after=N` returns `{"events": [...], "cursor": integer}`. Events are in increasing unique cursor order and have `cursor`, `external_id`, `listing_id`, `revision`, `amount`, `terms`. Cursor and revision are positive integers (at most 10^12 and 10^9); IDs are nonempty strings up to 64 characters, amount is integer 1..10^12 and terms is a nonempty string up to 2000 characters. Responses use only cursors greater than `after`; the returned cursor is at least `after` and every included cursor. Application event policy is a client decision.
- `GET /review/<encoded external_id>` is a real HTML offer page.

The Python fixture owner can append events, send actual callbacks and simulate failed reads; no HTTP admin endpoint is exposed to candidate programs. The provider accepts subscriptions and read requests; it has no offer-mutation API. Examples and environment scaffolding do not dictate the application's exact business policies.

## Browser behavior

Use the existing interface or an equivalent one with the published selectors: `#actor`, `#listings`, `#draft-form`, `#analysis`, `#sync`, `#offers`, `#notifications`. List and offer elements use `data-id` for their actual record IDs. The draft form controls use editable field names. Preserve `#new`, `#title`, `#comparables`, `#count`, `#tone`, `#analyze`, `#now`, `#message` so public browser automation can operate it. Render text safely and clear old views when changing identities. Layout and wording may differ. Offer links must be usable in the browser; reporting a link in an unused state object is insufficient.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
