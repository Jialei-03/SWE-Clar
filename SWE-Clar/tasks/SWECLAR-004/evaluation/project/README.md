# Local social and business network

Extend this independently reconstructed working browser application. It already serves a page, signs in synthetic accounts, edits profiles and stores interactions in SQLite. Complete discovery, relationship and membership behavior after clarifying the business rules with the client.

## Prepared environment

The benchmark supplies Python 3.12, SQLite and Chromium/Playwright in the `python-web` profile. There are no packages to install, external services, real accounts, original customer files or network downloads. The working directory is `/workspace`; the writable workspace limit is 512 MiB, memory 2 GiB, CPU 2, process limit 256. Only loopback networking is used.

Start `python app.py --db network.sqlite --fixtures fixtures/demo.json --port 8000` and open `http://127.0.0.1:8000`. Port `0` selects a free local port; print that port as the first stdout line. The service binds loopback. Stop with Ctrl-C. To reset, stop the service and remove your disposable `network.sqlite` (and any associated SQLite journal files), then start again. Starting against an existing database preserves its state and sessions. No build step is needed. Run `python /public_tests/test_public.py` for public checks. The manager runs the protected environment preflight before the task budget begins.

`app.py` handles HTTP, `storage.py` persists data, `policies.py` contains business behavior, and `web/` contains the real page. You may restructure code while preserving the command, HTTP and page interfaces below. Keep actual HTTP/SQLite/browser execution; JSON-only emulation of the page is insufficient.

## Synthetic input fixtures

`fixtures/demo.json` contains `accounts`, initial accepted `connections`, and demo `receipts`. Fixture accounts have unique `id`, `display`, `role` (`user` or `business`), `password`, `x`, `y`, and `interests`. Connection entries are two different account IDs. Receipt entries have unique `id`, `user_id` and `plan`; their presence means issued, not necessarily eligible for the logged-in account. All strings and credentials are synthetic. The benchmark may supply another valid fixture using the same schema through `--fixtures`. Read it at startup; never require a fixed account name, receipt ID or bundled example.

The demo has accounts `u1`–`u8` and `b1`–`b2`, with password `demo-` followed by the ID. Receipt IDs combine an account and a plan, for example `b1-local`; ask which plans and claims are allowed. Coordinates are a synthetic plane measured in kilometers. They are not real addresses or GPS coordinates. Demo receipts represent a local membership workflow; no money is collected, no real payment provider is contacted, and no payment-security guarantee is implied.

## Public HTTP contract

Responses are JSON except the HTML/CSS/JS page. Every successful API call returns HTTP 200. Errors have `{"error":{"code":...}}`: malformed input uses 400/`invalid`, missing or invalid authentication uses 401/`unauthorized`, disallowed business actions use 403/`denied`, and unknown resources use 404/`not_found`, except membership receipt claims. For POST `/api/subscribe`, an unknown/unissued receipt, another account's receipt, or a role-ineligible plan always returns 403/`denied` with no state change; this specific rule overrides the generic unknown-resource rule. Rejected operations leave stored business data unchanged. All POST/PUT bodies contain exactly the documented keys; do not accept extra actor, owner, author, plan or permission overrides. Valid request bodies are limited to 16 KiB. Actor identity always comes from `Authorization: Bearer TOKEN` after login.

| Method and path | Input | Output |
|---|---|---|
| GET `/health` | None | `{"ok":true}` |
| POST `/api/login` | `id`, `password` strings, exact fixture credentials | Nonempty opaque `token` and `user` |
| POST `/api/logout` | `{}` with token | `{"ok":true}`; revokes this token |
| GET `/api/me` | Token | `user` |
| GET `/api/people` | Token | `people`: ID-sorted `{id,display,role}` list |
| PUT `/api/profile` | `interests`, `x`, `y` | Updated `user` |
| GET `/api/matches?radius=10&role=all` | Token; optional radius default 100, role default all | `matches` list |
| POST `/api/connection` | `target` account ID, `decision`: request/accept | Boolean `accepted` |
| POST `/api/block` | `target`, boolean `blocked` | `{"ok":true}` |
| POST `/api/message` | `target`, `content` | New nonempty `id` |
| POST `/api/group` | `name` | New nonempty `id` |
| POST `/api/invite` | `group_id`, `target` | `{"ok":true}` |
| POST `/api/post` | `group_id`, `content`, boolean `featured` | New nonempty `id` |
| POST `/api/like` | `post_id` | Integer `likes` |
| POST `/api/subscribe` | `receipt_id` string | Current `plan` |
| GET `/api/dashboard` | Token | `connections`, `groups`, `posts`, `messages`, `blocked` lists |

A public `user` has `id`, `display`, `role`, `x`, `y`, `interests`, `plan`; never expose passwords, their hashes, session tokens or another user's private messages in discovery. Editing changes only the actor's profile. Interests are 0–10 distinct strings matching `[a-z][a-z0-9_-]{0,23}`; coordinates are finite numbers from -1000 to 1000 inclusive (booleans are invalid). Radius is finite and 0–3000 inclusive. Role filter is `all`, `user` or `business`; unknown/repeated query keys are invalid. Names and content are trimmed: group names 1–80 characters, message/post content 1–2000. A target must exist and connection/block/message targets differ from the actor. A valid group/post ID must exist. Every message, group and post creation gets a fresh ID, including repeated identical content.

Match records contain `{id,display,role,shared,degree,distance}`. `shared` and `degree` are integers and `distance` is an unrounded number; ask the client about their calculation and ordering. Dashboard connection records contain `target`, boolean `accepted`, boolean `incoming`. Groups contain `id`, `owner`, `name`; messages contain `id`, `sender`, `recipient`, `content`; posts contain `id`, `group_id`, `author`, `content`, boolean `featured`, integer `likes`. `blocked` is the actor's sorted block list. Dashboard arrays retain creation order except `blocked`; business visibility rules are clarified separately. Additional harmless metadata is allowed in returned records, but the request shape is exact. Unknown URLs must not serve the database, fixture passwords, application source or arbitrary local files.

## Public browser contract

Preserve a usable page with the same element IDs shown in `web/index.html`. Login uses `username`, `password` and form `login`; authenticated content lives in `workspace` and is hidden before sign-in. Identity and active plan appear in `identity` and `plan`. Forms `profile`, `discover`, `message-form`, `group-form`, `post-form` and `subscribe` invoke the corresponding real API. `target` selects an account and `group-select` selects a joined group. Buttons `request`, `accept`, `block`, `unblock`, `invite`, `logout` perform their named operations. `featured` is a checkbox. Keep each labeled field usable at 375 px and 1280 px without horizontal page overflow.

Render actual discovery results inside `results` with a `data-user-id` attribute for each result in server order. Render messages and posts in `messages` and `posts`, with `data-message-id` and `data-post-id`. Each post has a `Like` button and visible `Likes: N`. The page refreshes relevant lists and current plan after successful actions; form failures display the API error code in `feedback`. Display user-entered text literally. Successful message/post submission clears its content field; failed submission preserves it. Logout clears private lists and token state. You may change appearance and internal implementation while keeping these observation interfaces.

Ask the client about ranking and radius edges, relationship/blocked-user permissions, group access, receipt ownership/replay and featured-post policy. These are intentional business decisions; dependencies, fixture access and start/test commands are already provided.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
