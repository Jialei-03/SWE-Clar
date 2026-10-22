# Local intake service

Use `python server.py --db /tmp/intake.sqlite --port 8080` from /workspace.
GET /health and POST /events use loopback HTTP. Run public checks with
`python /public_tests/test_public.py`. Stop the server and remove the chosen SQLite
file to reset; restarts otherwise preserve data. Python standard library only.
The schema and records are synthetic; outbox entries do not send real messages.
Repair intake replay, cleanup and route stabilization while retaining match/notice behavior.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
