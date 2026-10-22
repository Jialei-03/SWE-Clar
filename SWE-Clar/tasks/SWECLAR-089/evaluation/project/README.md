# Lesson scheduling and credit backend

Repair this Python HTTP/SQLite backend and its studio provider adapter. `python server.py` starts a loopback API; PORT=0 selects an available port and prints it as JSON. Configure STUDIO_DB and STUDIO_CONFIG. The private runtime configuration holds initial_state, sessions (synthetic Bearer tokens mapped to users), provider_url and optional provider_token. POST /actions sends one JSON action and receives a scoped result or error, never the internal state. `process_music_action(state,action,service=None)` is the internal immutable workflow boundary.

Initial state holds users, packages (package IDs to lesson counts), credits, availability and booking/ledger records. Actions include set_availability, purchase_package, book, complete, cancel and portal. Availability slots use start/end ISO timestamps with timezone offsets. The starter includes durable storage, the request adapter, workflow rules and incomplete provider operations. Clarify scheduling, payment, notification and access rules as needed.

The benchmark executes real local HTTP requests against a synthetic provider. Its normalized payment/meeting/email protocol is not the native Stripe or Zoom API. Email acknowledgements mean an idempotent connector accepted a synthetic notification; no real email is sent. This is a reconstructed backend component, not the original commercial SaaS, its wireframes, production login service or account deployment.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
