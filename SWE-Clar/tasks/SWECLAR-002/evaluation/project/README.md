# Practice companion

Complete this independently reconstructed React Native Web / HTTP / SQLite application. Keep its working screens and public interfaces. Clarify subscription, media interaction, goal/report and session-lifecycle policies with the client. This is a browser task; mobile lock-screen behavior, native SDKs and real purchases are outside its scope.

## Prepared environment

The benchmark manager preinstalls Python 3.12, SQLite, Node 22.18, React 18.3.1, React Native Web 0.19.13, esbuild 0.25 and Chromium. No installation or external account is needed. `UI_NODE_MODULES` and `ESBUILD_BINARY_PATH` point to protected build dependencies. Network access is loopback only. CPU: 2; memory: 2 GB; workspace: 512 MB; temporary storage: 1 GB. Use regular source files and directories; symlinks in candidate source are rejected.

```sh
node build.mjs
PORT=8000 python server.py
python -I /public_tests/test_public.py
```

Open `http://127.0.0.1:8000` after launch. `PORT=0` requests a free port; the server prints its decimal port as the first stdout line. Rebuild after changing the UI. Stop your application, remove only its `practice.sqlite` database, and restart to reset your development records. Do not remove protected service files. Generated UI files belong in `dist/`. Normal logs may follow the initial port line; log diagnostics to stderr.

The preflight starts the synthetic receipt service and creates media/configuration. `PRACTICE_CONFIG` points to its readable config, `PRACTICE_ASSETS` to generated WAV files, `PRACTICE_DATABASE` to the application's writable SQLite path. The benchmark can replace these paths and local provider address with fresh fixtures using the same schema; never hard-code them. Development logins are `user-a` / `fixture-only` and `user-b` / `fixture-only`. Example receipt `demo-a` belongs to user-a, product `quarter`, channel `alpha`; `demo-b` belongs to user-b. These are public synthetic fixtures, not customer credentials.

Config: `users:[{id,login,password}]`, `products:{id:{title}}`, six distinct `questions:[{id,label}]`, `tracks:[{id,title,filename,playlists:string[]}]`, `provider` (loopback HTTP base URL), `provider_key` (hexadecimal synthetic signing key). Configured IDs and media filenames may vary. The application may read this config and media; business responses must not expose private configuration fields. Browser source should use the published API.

## HTTP contract

All JSON request bodies are objects containing exactly the fields below. JSON successes return 200. An error is `{error:string}`; wording is flexible. Invalid fields/types return 400, failed authentication 401, missing/unavailable resources 404, unsupported methods 405, conflicts 409, oversized bodies 413, invalid media ranges 416, provider operational failures 502. Body limit is 65,536 bytes. Unknown routes return 404; existing routes with unsupported methods return 405. Only `/` and `/app.js` are public static resources.

Authenticated routes use `Authorization: Bearer <token>`. Nonempty login/password strings have maxima 128/256 characters. Goal IDs use 1–64 ASCII letters, digits, underscores or hyphens; titles are nonempty after trimming and at most 120 trimmed characters. Transaction IDs are nonempty strings up to 128 characters, product IDs up to 64 and channel strings up to 16. The subscription business policy is a separate clarification. Survey answer maps use the configured question IDs and numeric values; clarify validation, aggregation and lifecycle decisions.

| Operation | Request | Success response |
|---|---|---|
| POST /login | `{login,password}` | `{token:string}` |
| GET /me | — | `{id:string}` |
| GET /products | — | configured product object |
| GET /tracks | — | `[{id,title,playlists}]`; no filename field |
| GET /questions | — | configured question array |
| GET /goals | — | `[{id,title,complete:0\|1}]` |
| POST /goals | `{id,title}` | `{id}` |
| POST /complete-goal | `{id}` | `{id,complete:true}` |
| POST /surveys | `{answers:{question_id:number}}` | `{id:positive_integer}` |
| GET /report | — | `{count:integer,latest:object,overall:object}` |
| POST /activate | `{transaction_id,product,store}` | `{transaction_id,user,product,store}` |
| GET /subscriptions | — | `[{transaction_id,product,store}]` |
| POST /logout | `{}` | `{}` |

GET `/audio/<percent-encoded track id>` returns original WAV bytes (`audio/wav`). The `Range` interface supports one `bytes=start-end` or `bytes=start-` range, with nonnegative decimal integers. Clamp end to the last byte; reject reversed or out-of-bounds starts and all other range forms. A valid range returns 206 with `Accept-Ranges: bytes` and `Content-Range: bytes start-end/total`; full content returns 200 with `Accept-Ranges: bytes`.

## Local receipt interface

Make a real HTTP GET to the configured provider's `/receipts/<percent-encoded transaction id>`. A successful response is `{payload:{transaction_id,user,product,store,status},signature}`. Canonical signing input is UTF-8 JSON of payload with keys sorted, compact separators, and non-ASCII characters escaped (`ensure_ascii=True`); signature is lowercase hex HMAC-SHA256 with the hex-decoded `provider_key`. The provider can return missing or unavailable responses. Clarify which signed receipts should activate, how repeated/conflicting transactions behave and how failures affect stored state.

## Browser interfaces

Preserve `data-testid` controls: `login`, `password`, `signin`, `logout`, `error`; `tab-audio`, `tab-goals`, `tab-survey`, `tab-results`, `tab-subscription`; `play-<track id>`, `pause`, `resume`, `playback`; `goal-title`, `add-goal`, `complete-<goal id>`, `goal-status-<goal id>`; `answer-<question id>`, `submit-survey`; `survey-count`, `latest`, `overall`, `score-<question id>`, `bar-<question id>`, `no-results`; `product`, `store`, `transaction`, `activate`.

Use an actual HTML audio element for playback. Visible `playback` text includes `Playing` or `Paused` and the numeric position in seconds. Report `survey-count` reads `Submissions: N`; scores show two decimals, and bar heights use a common linear zero-to-ten scale (choice of total pixel height is free). Empty-result wording is free through `no-results`. Existing labels and navigation may be styled freely. Do not replace actual API calls, media playback or graphs with self-reported status flags.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
