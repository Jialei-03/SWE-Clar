# Event matching backend component

Implement `process_matchmaker_command(state, command) -> dict` in solution.py. This bounded module handles local OTP verification, profiles, event registration, match permissions, messages, blocking and report records. Preserve the supplied SQLite CLI. It is not a full dating application or an SMS/Firebase integration. Actor IDs and organizer context are supplied by a trusted upstream caller; this command interface does not authenticate a network session.

Use prepared python-web (Python 3.12.3, standard-library SQLite), with no installation or external account. In /workspace run `python cli.py --db matchmaker.sqlite init` with one JSON state on stdin. `show` prints public state; `act` reads a command and prints its outcome. Each call is a separate process. Init cannot replace an existing database. Successful business state persists; rejected actions leave stored business state intact. Public check: `python /public_tests/test_public.py`. Limits: 2 CPU,2048 MiB,256 processes,256 MiB workspace; no external network.

State includes users/events/matches mappings and messages array; missing optional collections mean empty. Each user may initially have local phone/otp credentials. The CLI stores those fixtures separately in its auth table and reinjects them for later commands, including after rejected OTP attempts or other users' actions. Public state and all outputs must remove phone/otp fields and redact stored credential strings if reflected elsewhere. `cli.public_state` is supplied as a reusable projection helper. Do not mutate either function input. Return a new sanitized state with result or a nonempty error.code; preserve unrelated business data on errors. Additional metadata and alternate error strings are allowed.

Visible verification/profile rule: verify_otp matches a nonempty supplied string against the existing user's local OTP and sets verified=true. update_profile requires a verified user, nonempty dance_style/skill_level strings and preferred_role lead/follow. Store and return these three fields in result.profile. Extra command fields must not overwrite identity, approval or authentication fields. No OTP is sent externally.

Commands:

- verify_otp: user_id, otp.
- update_profile: user_id, dance_style, skill_level, preferred_role.
- create_event: organizer_id, event_id, capacity {lead,follow}.
- register_event: event_id, user_id, role.
- override_role: event_id, organizer_id, user_id, role.
- express_interest: user_id, target_id.
- send_message: sender_id, recipient_id, text.
- list_matches: user_id.
- block: user_id, target_id.
- report: user_id, target_id, reason.

User organizer approval is approved_organizer. Event records expose organizer_id,capacity,attendees,waitlist; registration entries contain user_id and role. Registration returns top-level registration_status. Match records expose users (two IDs) and active; keys and interest/block storage formats are free. list_matches returns result.matches. Messages expose sender_id,recipient_id,text. Internal reports and admin_alerts expose reporter_id,target_id,reason. These alerts are records, not delivered notifications.

Ask the client about organizer approval, capacity/waitlist transitions and overrides, when matches activate, chat visibility and blocking/report rules. Keep this a local persistent backend slice using synthetic records, not the original application or assets.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
