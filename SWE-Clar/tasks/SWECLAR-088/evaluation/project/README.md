# Local license backend
Implement process_license_action(state,action) as an immutable transition returning complete private state plus result or nonempty error.code. Invalid actions preserve business records except explicitly specified abuse-audit effects. Extra metadata/error wording accepted. SQLite cli.py --db PATH init/show/act initializes once, provides trusted operator inspection, or persists an action. act outputs only result/error; transient envelopes are not stored. Persist audited denials as specified by the policies.

purchase(event_id,license_id,license_key,email,shop,paid) is trusted local confirmed-event input. paid must be true, IDs/email/shop nonblank and key at least8 characters. Email/shop trim+casefold; email has one @ with nonempty whitespace-free parts. New license ID/key unique. Store active bound license using SHA256 key_hash and last4 key_suffix. Store one private deliveries outbox row with event_id,license_id,email,body containing its synthetic key,status=queued. Results omit raw keys/hashes. Exact normalized event replay returns original license_id and does not duplicate delivery, even with a different requested license_id. Changed event email/shop/key or unpaid replay rejects.

Other actions: verify(license_key,shop,ip,timestamp?,now?); trial(license_id,license_key,email,shop,now?,expires_at); set_status(admin_id,license_id,status); search(admin_id,query?). Clarify binding, audit, expiration and admin rules. state.admins contains trusted operator IDs. show/outbox are private operator storage; no public network authentication or actual mail/Shopify delivery is implemented.

Run python cli.py --db /tmp/licenses.sqlite init with {"admins":["admin"]} on stdin, then act with JSON operations. Python standard library only. All records and keys are synthetic; no original shops/emails/licenses are included.

Trusted CLI inspection protocol: `show` reads `{"admin_id":"admin"}` from stdin, where admin_id must name an entry in persisted state.admins. Return the complete persisted private state for an authorized operator; otherwise return a nonempty error.code without changing storage. This is a local synthetic operator identity, not a network authentication mechanism. `init` and `act` keep their existing stdin schemas.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
