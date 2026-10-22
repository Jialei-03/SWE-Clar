# Membership policy module

Extend a local account and commerce library. Account creation/inactivation and a JSON command-line adapter already work. Implement cart, checkout, settlement and renewal policies. Payment records are instructions for a hypothetical caller; no actual card charge, OAuth, payment website or commercial project deployment is required. Ask the client about pricing, coupons, settlement and renewal decisions.

## Run and reset

The prepared Python environment uses standard library dependencies. From `/workspace`, run `python solution.py < examples/account.json`; run public regressions with `python /public_tests/test_public.py /workspace`. The CLI reads one JSON object containing `state` and `action`, and emits one JSON state on stdout. Each call is independent; reset by supplying fresh state. No persistent service, external account or network is needed. Resource limits are in the task environment manifest.

## Public interface

`solution.process_membership_action(state: dict, action: dict) -> dict` returns deterministic JSON and must not mutate either input. File/module layout is otherwise free. Preserve unrelated state fields. `result` and `error` are transient envelopes replaced by the next call. Successful results may include additional fields. A rejected request returns a nonempty string `error.code` and preserves all business state; the exact error-code spelling is not prescribed.

State contains maps `users`, `products`, `coupons`, `carts`, `orders` and arrays `ledger`, `payments` (missing empty containers may be initialized). IDs are arbitrary caller-supplied strings. User records use `email`, `phone`, `provider`, `status` (`active`/`inactive`), `membership` (`free`/`paid`), `credits`, and optional ISO `credit_expiry`. Products use integer `price_tl` (synthetic whole money units), integer `credits`, optional boolean `active`. The legacy label TL is only a synthetic currency token. Coupons use `active`, integer `amount_tl`. Prices and credit costs are nonnegative; quantities are positive integers. Tests use valid ISO calendar dates and integer amounts, without external exchange rates.

| Action type | Input fields | Relevant output |
| --- | --- | --- |
| create_account | user_id, email, phone, provider | users[id], result.user_id |
| delete_account | user_id | users[id].status |
| set_cart | user_id, items: [{product_id, quantity}] | carts[user_id] and result: items, total, currency, coupon_visible |
| checkout | user_id, order_id, optional coupon_code, optional kind (`regular` default or `membership`) | orders[id] and result: order_id, payment_required, thank_you |
| settle | order_id, event_id | orders[id], users[id], ledger, payments |
| renew | user_id, event_id, date, new_expiry, package_credits | users[id], ledger |

A cart has `items`, `total`, `currency` (`TL`/`credits`), `coupon_visible`. An order has `user_id`, `total`, `currency`, `kind`, `status` (`pending`/`settled`), `thank_you`, `payment_required`. Supplied order/cart seeds follow this public schema. Callers can provide already-created orders; settlement must not depend on private state from account creation or checkout. `kind` distinguishes purchase routing only; renewing the membership uses `renew`.

Settlement ledger entries contain `event_id`, `order_id`, `kind: settlement`; renewal entries contain `event_id`, `user_id`, `kind: renewal`. Additional record fields and internal bookkeeping are allowed. A shortfall payment record contains `kind: saved_payment_topup`, `event_id`, `order_id`, `credits` (shortfall). A nonzero money-order settlement produces a `regular_payment` record with `event_id`, `order_id`, `amount_tl`. These are synthetic records only. Thank-you route tokens are `coupon`, `regular`, `credit`, `membership`.

## Existing account behavior

Create supports `email`, `social` and `fast_checkout` providers using the supplied stable user ID. Repeat creation preserves existing contact details and does not reactivate inactive accounts. Deletion marks an existing account inactive. An optional accidental `card` object on account creation must be ignored, including its sensitive values. No raw card data belongs in returned state. The supplied account example uses synthetic contact values.

## Scope of validation

Reject missing/inactive users for commerce actions, missing/inactive cart products, nonpositive quantities, missing carts and unknown orders, without changing business records. All other input schemas above are valid in the benchmark. Cart and checkout rules, coupon routing, settlement replay and credit rollover/expiry are business decisions available through clarification. Public tests cover the provided account lifecycle and CLI, not the undisclosed commerce decisions.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
