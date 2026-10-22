# Creature arena component

Complete the gameplay functions in this independently constructed browser prototype. The supplied HTTP service, canvas scene, movement controls and inventory/fusion panels already connect to one application state. Implement `process_game_action(state, action) -> dict` in `solution.py` while preserving actual interaction and rendering. Use synthetic scenario data and simple generated geometry; no original game, assets, accounts or engine installation is required.

Work in `/workspace` with prepared `python-web`. Start `python server.py --port 8080`, then open `http://127.0.0.1:8080/`. `/health` checks the server. Arrow keys move the player when the canvas has focus; buttons invoke gameplay actions. Reset with the page button or `POST /reset`; restarting also reloads `scenario.json`. Python standard library and the prepared browser are sufficient. No dependency installation is part of the task.

`GET /state` returns current state. `POST /action` accepts a JSON object and returns new state with `result` or a nonempty `error.code`; HTTP success is 200 and rejection 400. Keep both input objects unchanged. Errors preserve existing business state. Extra metadata and alternative error codes are allowed unless a specific code is explicitly stated in the full requirements. Unknown or malformed operations must leave the service usable.

State mappings are `combatants`, `skills`, `inventories`, `creatures`, `recipes`, and `drops`; `events` is a list. Combatants have `hp`, `level`, `defense`; skills have `power`; inventories have fixed `capacity` and `slots` containing `item_id` and `quantity`. An item description has `item_id`, `stackable` and, for stackable items, `stack_limit`. Each recipe has `level`, two `inputs` creature types and a `result` creature type. Owned creatures are a list of type strings for each user. These are synthetic gameplay records, not user identities.

Actions: `use_skill(source_id,target_id,skill_id)`, `add_item(user_id,item,quantity)`, `roll_drop(enemy_id,drop_id,roll,chance,owner_id,now,item)`, `pickup(drop_id,user_id,now)`, `expire(now)`, `encyclopedia()`, and `fuse(user_id,recipe_id)`. Time is supplied in seconds; the browser uses its clock, while tests can supply deterministic values. Probability rolls are supplied to separate game rules from a random-number generator. The sample loot control uses a guaranteed roll for demonstration.

Skill results expose `damage` and `target_hp`. Drop and pickup results expose `dropped` and `picked`; world drops must be removed or marked `picked`/`expired` when no longer available. Encyclopedia results contain a `recipes` list, with each entry including its `recipe_id` and configured fields for the selector. Successful gameplay changes must appear in the actual health bars, world loot, inventory and creature panels. Ask the client about damage rules, stacking, pickup/expiry windows and fusion eligibility.

This is a bounded battle, loot, inventory and fusion slice, not a complete commercial game or a recreation of its original 3D maps. Limits: 2 CPU, 2048 MiB memory, 256 processes and 256 MiB workspace. Execution networking is loopback only; runtime dependencies and environment checks are supplied before the agent budget.

Public verification: `python /public_tests/test_public.py`. The prepared python-web profile supplies Python 3.12.3, Playwright and Chromium; no installs are needed. The optional `/public_tests/browser_worker.py` reads a JSON session on stdin and records real browser operations. Numeric inputs must be finite and cannot be booleans. Quantity must be a positive integer. A drop contains one item; pickup must actually place it in the player's existing inventory. Invalid/overflow operations preserve all business state.

Time advances only through supplied actions: expire(now) is explicit; unsuccessful pickup preserves the world drop. Additional metadata does not need to have a prescribed format.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
