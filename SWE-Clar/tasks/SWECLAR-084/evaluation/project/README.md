# Local coaching directory backend
Implement process_coaching_action(state,action) in solution.py. Return a new internal state with result or nonempty error.code; preserve input objects and business state on rejection. Extra metadata and alternate errors are accepted. SQLite CLI --db PATH init/show/act persists successful changes across invocations; init cannot overwrite state; act emits only result/error. show is local operator inspection. Operation user IDs are trusted upstream context, not an unauthenticated public network interface.

Initial users maps IDs to coach/athlete roles. Optional dictionary collections: credits,services,sessions,plans; list collections: checkins,reviews,messages. Incorrect collection types reject.

publish_service(coach_id,service_id,specialty,modality,price,slots): coach only, unique nonempty ID, nonblank specialty, online/in_person/hybrid, finite nonnegative price excluding bool, nonempty nonblank string slots. Trim specialty/slots; dedupe slots preserving order. Store service active=true. discover(specialty?,modality?) returns active services; specialty case-insensitive trimmed substring; exact supported modality. Order casefolded specialty then service_id. Result.services includes service_id and service fields.

Further operations: book(athlete_id,service_id,session_id,slot,purchase_type); assign_plan(coach_id,athlete_id,plan_id,plan_type,content); checkin(athlete_id,plan_id,week,content); complete_session(coach_id,session_id); review(athlete_id,session_id,review_id,rating); message(session_id,message_id,sender_id,recipient_id,text); view_session(actor_id,session_id). Clarify credit, session lifecycle, relationship and replay rules as needed.

This is a bounded synthetic backend. Purchases are local intents; no live billing, full mobile marketplace, coach profile import, or medical/nutrition advice generation. Plan content is supplied synthetic data and stored unchanged.

Run python cli.py --db /tmp/coaching.sqlite init with {"users":{"coach":{"role":"coach"},"athlete":{"role":"athlete"}},"credits":{"athlete":1}} on stdin, then act with an operation. Python standard library only.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
