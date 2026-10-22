Internal role note: the operation adapters and regression suites under /public_tests are evaluator-only, not freelancer development commands. Do not disclose their source or advise the freelancer to run them. For a requested local check, explain the relevant application interface and use independently written Flutter widget tests with `flutter test --no-pub`.

# Appointment maintenance application

This is independently authored Flutter application code with synthetic Clinics, Providers and Bookings data. Extend its relationship handling and maintenance workflow while preserving working browsing and real HTTP/database behavior. Business decisions about legacy relationships, migration integrity and repair completion are available through clarification.

The benchmark provides Flutter 3.47.2, Dart 3.13.2, locked dependencies including `http 1.6.0`, real Flutter widget rendering with public SDK fonts, and Firestore Emulator 1.19.8. The local service is already running at `http://127.0.0.1:8080`, project `demo-sweclar`. Its initial example records are reproduced in `assets/demo_documents.json`. Runtime preparation, Java/SDK installation, downloads and service health are the benchmark's responsibility.

## Work and checks

Work in `/workspace`. Every attempt has a fresh writable workspace and demo database. There is no external network or production account. Resources are 2 CPUs, 2 GiB memory (including a 384 MiB Java heap), 256 processes, 512 MiB workspace and 1 GiB temporary storage. Keep the package name `appointment_fixture` so public tooling can import the application. Dependencies are resolved offline from protected sources; the workspace and temporary directory are not executable. Flutter/Dart binaries are already installed in executable protected paths.

- Resolve application metadata: `flutter pub get --offline --enforce-lockfile`.
- Run visible regression checks: `python /public_tests/test_public.py`.
- Render and operate the app: `python /public_tests/run_maintenance.py --script session.json --output /tmp/maintenance-preview`.
- Run the command-line migration: `dart run tool/migrate.dart http://127.0.0.1:8080 providers clinic clinics`.
- Read development service logs: `/tmp/sweclar-firestore-development/firestore.log`.
- Restore the public demo records: `python /public_tests/run_maintenance.py --reset-demo`. This is an explicit destructive reset of the current disposable development database, not part of evaluation.

For example, create `session.json` containing:

```json
{"operations":[{"op":"mount"},{"op":"tap","key":"nav-providers"},{"op":"capture","name":"providers.png"}]}
```

The output directory contains observations and PNGs from actual Flutter rendering. This is a local component runner; it does not claim a mobile device build, native background service, store release or real customer authentication. Source changes are compiled on each operation session. The benchmark's independent preflight runs before candidate work; public checks are useful during normal development.

## Repository and data interface

Keep `lib/maintenance.dart` exporting `FixtureRepository(String base, {http.Client? client, String project='demo-sweclar'})`. Honor the supplied HTTP client so local request failures and delays can be exercised using the same protocol. Expose `getDocument(String path)`, `list(String collection)`, `view(String collection)`, `normalize(String collection,String field,String targetCollection)`, and `close()`. Methods return futures except `close`. `getDocument` receives `collection/id`, returns a typed document or null on 404 and throws on other errors. `list` follows every `nextPageToken` and returns every typed document, including `name`, `fields` and `updateTime`.

The real REST prefix is `/v1/projects/demo-sweclar/databases/(default)/documents`. A document has its full resource `name`, `fields` encoded using Firestore Value objects, and server-generated timestamps. Common values include `{"stringValue":"text"}`, `{"referenceValue":"projects/demo-sweclar/databases/(default)/documents/clinics/clinic-a"}` and `{"mapValue":{"fields":{"id":{"stringValue":"clinic-a"}}}}`. Other ordinary typed values can appear in unrelated fields. Example data are synthetic; collection names and exact relation policies are independently designed for this task.

`view` accepts `clinics`, `providers` or `bookings` and returns rows with string `id` and `name`, nullable string `relation_id` and nullable string `relation_name`. Clinic rows have no relation; provider rows concern `clinic`; booking rows concern `provider`. The intended compatibility rules, label fallback and ordering can be clarified. Additional harmless metadata are allowed. Reading must not change stored documents.

`normalize` returns report rows with `document`, `field` and `reason` string fields, or throws when it cannot complete. Configuration identifiers match `[A-Za-z_][A-Za-z0-9_]*` and invalid configuration must not write. Source/target document IDs use letters, digits, underscores and hyphens. Fixtures contain at most 200 source documents; target records remain stable during a migration. Required relation conversion, dangling handling, preservation, conflict and repeat policies should be clarified. Preserve records and unrelated fields. Do not report success when a real read/commit failed.

## Widget interface and existing regression obligations

Export `FixtureApp({required FixtureRepository repository})` from `lib/app.dart`; `lib/main.dart` starts it using the prepared endpoint. The caller owns the repository and closes it after unmounting. Keep these string ValueKeys on the corresponding controls/content so the operation adapter can exercise actual widgets:

| Keys | Content or action |
|---|---|
| `nav-clinics`, `nav-providers`, `nav-bookings` | Working navigation controls |
| `page-title` | Current collection ID as visible text |
| `refresh`, `repair` | Refresh current page; repair provider relations |
| `record-list`, `record-ID` | Scrollable record list and each record card |
| `id-ID`, `name-ID`, `relation-ID` | Literal ID, name and non-null relation label |
| `load-state` | Visible `loading`, `ready` or `error` |
| `empty-state` | Visible message after successful empty read |
| `repair-state` | Visible `idle`, `pending`, `success` or `error` |
| `repair-progress` | Visible progress while repair is pending |
| `repair-count` | Numeric dangling count for a successful repair |

IDs in row keys are actual document IDs. Keyed content may contain multiple Text children and unrelated explanatory wording outside the state/count values. Styling, internal widget structure and extra metadata are free. Controls and lists must be reachable at 360x950 and 768x950 logical pixels without overflow or render errors; scrolling is allowed. Names and labels are literal text. Keep empty results, read-error feedback and refresh/retry usable. Navigation must query the selected collection and discard stale earlier responses. No earlier page's records may overwrite the selected page. Repair workflow policies are available by clarification.

The public transport supports `mount`, `view`/`list` with `collection`, `get` with `path`, `normalize` with `collection`/`field`/`target`, `tap` with `key`, `viewport` with `width`/`height`, `scroll` with `dy`, `capture` with a PNG basename, and `inspect`. `fail` supplies `method` (`GET`, `POST`, or null to clear) for controlled HTTP 503 responses. `hold` supplies a method whose requests wait, optionally restricted by `path_contains`; `release` resumes them. These operations are testing facilities, not hidden business requirements. Observations include actual keyed text, button availability, request activity and candidate errors. The transport does not contain the private expected results.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
