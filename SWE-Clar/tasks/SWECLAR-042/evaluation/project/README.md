# Review assignment, fee allocation and approval-ledger module

Implement `process_review_action(state, action)` in `solution.py`. The supplied SQLite adapter and console work; the domain function currently leaves state unchanged. This task handles synthetic review-workflow records and an approval ledger. It does not transfer money or upload photos. Actor fields represent authenticated identity supplied by an upstream service; implementing that login service is outside this component.

The benchmark prepares Python and SQLite using the shared `python-web` environment. From `/workspace`, run `python cli.py runtime/ledger.db < example.json`. The request contains `seed` and `action`; the seed is used only when the database has no saved workflow. A new invocation restores the last successful state. Use a new database filename to start a fresh local scenario. `node`, web services and external accounts are not required. Run `python /public_tests/test_public.py` for public console/storage checks.

State contains `users` keyed by user ID, `sessions` as active user IDs, and numeric `fee_rate`. Workflow collections are `listings`, `applications`, `reviews`, `payments` (objects keyed by their respective IDs), `payouts` (list), and `processed_events` (list of payment event IDs). Missing workflow collections start empty. IDs and asset references are synthetic strings. Amounts are nonnegative decimal currency values with at most two decimal places. `fee_rate` is a supplied fraction between zero and one.

The public action envelopes are:

| type | fields |
|---|---|
| create_listing | listing_id, owner_id, price |
| apply | application_id, listing_id, reviewer_id |
| accept | application_id, owner_id |
| submit_review | review_id, reviewer_id, images (list of image-reference strings), optional url |
| payment | event_id, listing_id, payer_id, amount |
| approve_review | listing_id, owner_id |
| profile_image | user_id, image_ref |
| delete_account | user_id |

Application IDs also identify their associated reviews. Listing records contain `owner_id`, `price`, `status`, and, after acceptance, `active_review_id`. Applications contain `listing_id`, `reviewer_id`, `status`; reviews contain `listing_id`, `reviewer_id`, `status`, `images`, and optional `url`. Payment records include `event_id`, `listing_id`, `payer_id`, `receiver_id`, `gross`, `platform_fee`, `eligible`, `status`. Payout records contain `event_id`, `listing_id`, `receiver_id`, `amount`. These linkage and envelope fields are public; submission rules, fee processing and approval conditions can be clarified.

The `payments` object is keyed by payment `event_id`, not listing ID. Error codes must be nonempty strings; no particular spelling is required for rejected actions.

Return the next state as a JSON object. Rejections return `error.code` and are not persisted. Optional `result` fields describe action output; submission uses `image_count` and Boolean `url_skipped`. Additional nonconflicting metadata is allowed. Caller inputs remain unchanged. Payment credentials passed as incidental action data must never be copied into returned or stored state.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
