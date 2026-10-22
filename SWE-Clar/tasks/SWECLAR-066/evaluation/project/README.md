# Three-dimensional geometry escape room

Complete apply_escape_room_action(state,action) in solution.py and preserve the real browser game. The supplied native WebGL scene uses a fixed perspective camera, depth, walls/floor, two geometric clues, lock indicators and an exit. Count the gold and blue cubes for one answer; inspect the tetrahedron's wireframe vertices for the other. Submit answers through the controls, unlock both seals, then leave. Do not replace the scene or controls with solved flags or plain text records. All geometry, clues and wording are independently synthetic; this is one small room, not the original commercial 3D games.

Use prepared python-web (Python3.12.3, Playwright/Chromium), no dependencies/accounts/assets to fetch. In /workspace run `python server.py --port 8080`. `/game` is the playable room; `/embed` is a local host with an actual iframe of it. `/health` reports startup, `/state` returns application state, `/action` accepts one JSON action, `/reset` resets the scenario. Rejected actions return HTTP400 with nonempty error.code; accepted actions return200 and updated state. Extra metadata and alternate error wording are allowed. Public check: `python /public_tests/test_public.py`. Resource limits:2 CPU,2048 MiB,256 processes,256 MiB workspace; loopback only.

State includes puzzles (ID to configured answer), required_puzzles, solved, exit_open, escaped, texts (locale to key/string mapping), presentation, rotate_prompt and aspect_supported. Scene geometry and the synthetic scenario must remain consistent. Both function inputs remain unchanged; invalid actions preserve existing gameplay state. Puzzle answers are configured strings. Correct answer comparison trims surrounding whitespace. Unknown puzzle or incorrect answer rejects; repeat correct submission cannot duplicate solved entries. Exit opens exactly when every required puzzle is solved. The exit action then sets escaped=true and the page visibly completes the room.

Actions:

- solve: puzzle, answer, obtained from the actual answer field.
- exit: no other fields.
- viewport: width,height (finite positive numbers, not booleans).
- presentation: mode.
- text: locale,key; returns top-level text.

The browser reports actual viewport dimensions, selects a presentation for standalone/iframe play, and refreshes visible strings from backend lookup when the locale selector changes. Keep the16:9 canvas display area and actual3D rendering. Ask the client about rotation/aspect behavior, supported presentation modes and localization fallback. Shape dimensions, the two answers and local host are synthetic engineering fixtures. No customer model, story, source translation or remote URL is included.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
