Internal role note: the operation adapters and regression suites under /public_tests are evaluator-only, not freelancer development commands. Do not disclose their source or advise the freelancer to run them. For a requested local check, explain the relevant application interface and use independently written Flutter widget tests with `flutter test --no-pub`.

# Booking workspace

Complete this independently authored Flutter booking and local message client. It already has real Home, Bookings and Messages widgets, a controller, a JSON file store, navigation links and booking creation. Back-stack behavior, booking updates, and message/administrative operations need completion. Clarify their business rules with the simulated client. All users, content, screens and business data are synthetic.

The prepared `flutter-component` environment contains Flutter 3.47.2, Dart 3.13.2, locked packages, the Linux AMD64 widget engine and fonts. The SDK and package sources are protected. The manager provisions and checks this environment before your budget starts. Do not install tools or fetch services. This task evaluates an actual Flutter client component with local file persistence; platform tags select component availability, and do not represent native builds, signing, store deployment or remote message delivery.

## Run, inspect and reset

Work in `/workspace`. `flutter pub get --offline --enforce-lockfile` resolves the supplied lock file from preinstalled packages. `flutter test --no-pub` runs your own tests once added. `python /public_tests/test_public.py` runs the published regression checks. The manager's independent environment check is `python /opt/sweclar/preflight.py` and runs before grading.

For an actual UI preview, write a JSON session file and run `python /public_tests/run_booking.py --script session.json --output /tmp/booking-preview`. The public adapter renders the real Flutter widgets, taps controls, enters text, invokes controller methods and exports PNGs plus observations. Its operation schema and example are in `/public_tests/README.md`. Each invocation starts a fresh process and private local state; use `restore` within the session to test persisted state. Re-run for a clean reset. The output directory contains observations and any requested captures. No HTTP service, account or device connection is needed.

Limits: 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace and 1 GiB temporary space, no external network. Hidden evaluation uses the same operation adapter and toolchain; only its inputs and external assertions are private. Keep `/public_tests` and SDK files unchanged. You may modify project source and add tests; any optional dependency must already exist in the prepared locked package set.

## Interfaces and data

Preserve `lib/controller.dart`, `lib/booking_app.dart`, package name `booking_workspace`, and these callable interfaces:

- `BookingController(initial, storage, {required actorId, platform='android'})` extends `ChangeNotifier`.
- `Future<bool> act(Map<String,dynamic> action)`, `Future<void> restore()`, `Map<String,dynamic> get snapshot`, `List<Map<String,dynamic>> screens()`, and public `actorId`, `platform`, `busy`, `error` properties.
- `BookingStorage.save(state)` and `load()` are asynchronous. `FileBookingStorage(File(path))` persists actual JSON using a temporary sibling and atomic rename.
- `BookingApp(controller: controller)` renders the supplied controller. All operation methods and file paths are available from the outset.

`assets/initial_state.json` supplies a valid synthetic state. The manager may construct other valid states of the same schema. Initial state, saved state and actions contain JSON values. The required fields are:

```text
screens: {screenId: {title: string, design_ref: string, platforms: string[]}}
users: {userId: {role: "member" | "admin"}}
route: screenId
history: screenId[]
bookings: {bookingId: {participants: userId[], extension_minutes: integer,
                     extended: boolean, confirmed: boolean, status: string}}
messages: {messageId: {booking_id: string, sender_id: string,
                      recipient_id: string, text: string}}
audit: {eventId: {booking_id: string, actor_id: string, status: string}}
```

The three page IDs are `home`, `bookings`, `messages`; titles, registry order, platform lists and user IDs can vary. Platform tags are `android`, `ios`, `web`. The actor and their role come from the constructor plus trusted initial user registry, never from action-supplied identity or role fields. The local component is not a server authentication system.

Actions use `type` plus these fields. This table publishes the complete input shapes, not the undisclosed business decisions:

| type | fields |
|---|---|
| `navigate` | `screen_id` |
| `back` | none |
| `create_booking` | `booking_id`, `peer_id` |
| `extend` | `booking_id`, `minutes` |
| `confirm` | `booking_id` |
| `message` | `booking_id`, `message_id`, `recipient_id`, `text` |
| `admin_status` | `booking_id`, `event_id`, `status` |

Use string IDs without normalization; valid IDs contain at least one non-whitespace character. Required missing/invalid action fields must reject the action rather than partially mutating state. Unknown action fields do not confer authority. Extra harmless metadata in state/result objects is allowed; preserve required business fields and existing records.

## Public regression obligations

Isolate constructor input, actions, snapshots and screen-list results with independent copies. Caller edits must not mutate controller state. Compute each action without mutating current state; persist an isolated proposed copy before publishing the new snapshot. A save failure returns `false`, sets `error` to `storage_failed`, and preserves prior state. Successful actions return `true` and clear the previous error. `busy` is true during an outstanding save; another action returns `false` without adding a write. Finish with `busy=false` and notify widgets. Storage callers may retain their received argument, so later edits to it must not mutate the controller. `restore()` loads an existing valid saved state; absence preserves the current state. The test store supplies valid saved JSON or an explicit storage failure; corrupt-state recovery and competing processes writing the same file are outside scope.

Booking creation requires a known actor, a known distinct peer, and an unused nonblank string booking ID. It creates the two participants, zero extension minutes, `extended=false`, `confirmed=false`, `status=draft`; reject invalid creation as `invalid_booking`. Unknown actors and action types report `unknown_actor` and `unknown_action` respectively. Screen choices filter by the constructor's platform and sort IDs ascending. Navigation to an unregistered/unsupported screen reports `unknown_screen` and preserves state. Clarify the history/Back policy separately.

Preserve real editable widgets and controls at 360×950 and 768×950 logical pixels, with scroll access when needed and no render exceptions. The public observation keys are: `back`, `nav-home`, `nav-bookings`, `nav-messages`, `booking-id`, `peer`, `create`, `minutes`, `extend-<bookingId>`, `confirm-<bookingId>`, `complete-<bookingId>`, `chat-booking`, `recipient`, `message`, `send`, `booking-<bookingId>`, `status-<bookingId>`, `message-<messageId>`, `error`. Keep keys for the corresponding controls; labels and styling can change. A booking card must visibly include its ID, status and extension minutes; a saved message must visibly include its literal body and sender/recipient. The interface must reflect accepted changes and preserve the previous view after rejected changes. Error text reflects `controller.error`. Message/admin buttons create a new unique operation ID for each new user intent. Clarify who may operate or see each record and how repeated event IDs behave.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
