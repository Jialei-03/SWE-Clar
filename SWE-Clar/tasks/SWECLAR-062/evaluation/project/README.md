# Recurring service backend module

Implement `process_tasker_action(state, action) -> dict` in solution.py. Preserve the supplied SQLite command-line interface. This is a bounded web-backend policy component for quotes, monthly agreements, invoices, supplied payment events, categories and admin navigation records. It has no external payment provider, authentication service or full marketplace UI. Payment records never imply money was charged or settled.

Use the prepared python-web environment (Python 3.12.3, SQLite standard library). No installs or accounts are needed. Work in /workspace. `python cli.py --db workflow.sqlite init` reads one JSON state from stdin; `show` prints stored state; `act` reads one JSON action and prints the resulting state. Each invocation is a separate process. Init may not overwrite an existing state. Successful actions persist atomically; rejected actions print error.code without replacing stored state. The CLI creates its database locally and remains usable after malformed input. Run `python /public_tests/test_public.py` for public checks. Resources: 2 CPU, 2048 MiB, 256 processes and 256 MiB workspace; no external network.

State contains mappings clients, taskers, invitations, orders, invoices, categories and a payments array of accepted synthetic event IDs. Missing optional collections mean empty. Preserve unrelated records and both input objects. Return new state plus result on success or nonempty error.code on rejection; extra metadata and different error wording are allowed. Monetary amounts and rates must be finite numbers, not booleans. No prescribed decimal rounding is required.

Public recurring quote rule: only prior completed work for the same tasker qualifies for its recurring discount. History is clients[client_id].completed_orders[tasker_id]; rate is taskers[tasker_id].recurring_discount in [0,1]. With at least one prior completion, multiply the nonnegative amount by (1-rate); otherwise use the original amount. Return result.amount, discount_rate (applied rate), recurring (eligibility), subscription=false. Action flags or an agreement are not completed work; subscribe-and-save is separate.

Actions and fields:

- quote: client_id, tasker_id, amount.
- invite_monthly: invitation_id, client_id, tasker_id, monthly_amount, months.
- accept_monthly: invitation_id, client_id, order_id, first_due.
- issue_invoice: order_id, now.
- pay_invoice: invoice_id, event_id.
- add_category: category_id, optional parent_id.
- admin_tabs: role (trusted upstream context, not authentication from the CLI).

Created invitations expose their agreed IDs, monthly_amount and months; accepted orders also expose status and first_due. Quote/invitation/order/invoice outputs identify the created object in result (invitation_id/order_id/invoice_id). Invoice records expose order_id, sequence, amount and status. Categories expose parent_id and depth. Admin tabs expose name and route. Internal event association/counter formats are implementation choices. Ask the client about agreement uniqueness, duration, invoice scheduling and payment replay, category limits and administrative access.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
