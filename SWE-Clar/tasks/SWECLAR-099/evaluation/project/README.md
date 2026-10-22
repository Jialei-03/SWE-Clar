# Photo request component

An independently reconstructed browser photo-chat component and Python/Pillow/SQLite HTTP service. The benchmark supplies Linux Chromium and dependencies. No native device, camera, contact-directory access, notification delivery, external account or macOS service is needed.

Start `python /public_tests/demo.py`, then open its printed loopback URL. Synthetic users user-a through user-e use synthetic-passphrase. Select a room, create an Ask/Duo/Challenge request, sign in as a recipient, select a request, wait three seconds, and upload a supplied JPEG. Refresh renders decoded photos. Test helpers supply synthetic images; no personal photos are necessary.

Public interface: server.py binds PORT to loopback and prints the actual integer port; PHOTO_CONFIG, PHOTO_DATABASE and PHOTO_ASSETS specify fixture/configuration and writable state. GET / serves index.html. Keep the documented accessible form labels and actions for browser automation; internal functions and layout techniques may change.

HTTP JSON: POST /login {user,password} returns token. Authenticated requests use Authorization: Bearer token. GET /rooms, /requests?room=ID, /timeline?room=ID and /contacts return arrays. POST /requests accepts id, room, mode and caption; identical retries are idempotent and conflicts fail. Ask/Challenge target other members, Duo includes the sender. POST /open {request} begins a three-second server countdown; POST /respond {request,image} uploads base64 JPEG. Server timestamps determine eligibility within the 60-second window; later photos remain ordinary timeline entries. Images are decoded/re-encoded to remove metadata. GET /photos/ID requires membership. POST /contact {numbers} matches only selected numbers (+international or 00 prefix; spaces/hyphens/parentheses ignored), returns added users or a local invite action. GET /route?room=ID&request=ID validates both IDs and membership. SQLite and photo files must survive restart.

The browser provides login, room selection, request creation/opening, JPEG upload, selected-contact matching, request routing, timeline and a two-column group image grid. Only eligible images appear in the group grid. Clarify any unspecified placement of an incomplete row. These are component-level browser functions, not a full production messenger.

## Public browser automation interface

The existing DOM IDs are stable evaluation interfaces: `#login`, `#room`, `#create`, `#requests`, `#selected`, `#upload`, `#contact`, `#contact-result`, `#route`, `#route-result`, `#timeline`, `#grid` and `#status`. Preserve the corresponding existing form control names (`user`, `password`, `mode`, `caption`, `image`, `numbers`, `request`) and accessible button names. Request entries are actionable buttons; timeline/grid photos expose real `img` elements with captions in `figure`/`figcaption`. These hooks let the evaluator interact with the component and measure rendered image geometry. Internal functions, data structures and CSS techniques may differ; no particular centering implementation is required.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
