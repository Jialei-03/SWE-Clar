# Public Flutter operation adapter

The default viewport is 360×950 logical pixels. The adapter drives actual Flutter widgets and controller methods in a fresh process, with a fresh local JSON file and writable user cache. It contains no hidden business assertions. `test_public.py` supplies public regression assertions; `run_booking.py` is an observation/preview command, and successful transport does not mean business requirements pass.

Example `session.json`:

```json
{
  "actor": "member",
  "platform": "android",
  "operations": [
    {"op": "viewport", "width": 360, "height": 950},
    {"op": "mount"},
    {"op": "tap", "key": "nav-bookings"},
    {"op": "enter_text", "key": "booking-id", "text": "workshop-a"},
    {"op": "tap", "key": "create"},
    {"op": "capture", "name": "booking.png"}
  ]
}
```

Run `python /public_tests/run_booking.py --script session.json --output /tmp/booking-preview`. Read `/tmp/booking-preview/observations.json` and view `booking.png`. Use a new/empty output directory for each invocation. With no `initial`, the script uses the project's synthetic `assets/initial_state.json`; otherwise supply a complete initial state. A new invocation resets state; each operation within an invocation sees the preceding successful changes.

| Operation | Parameters / behavior |
|---|---|
| `viewport` | `width`, `height`: logical Flutter dimensions |
| `mount` | Build the real BookingApp and settle its frame |
| `tap` | `key`: the public control's string key; scroll into view and tap with real file I/O enabled |
| `enter_text` | `key`, `text`: edit a real text control |
| `act` | `action`: invoke the public controller action and record its boolean result |
| `inspect` | Record the current snapshot, screen list, errors, write count and visible widget text/keys |
| `hold_storage` | Hold the next save for a concurrency observation |
| `begin_act` | `action`: begin an action without waiting for its held save |
| `finish_act` | Release the held save and await that action |
| `fail_storage` | `value`: simulate a save failure before the real file store commits |
| `file_storage_probe` | Exercise FileBookingStorage in an isolated directory; observe whether saving preserves the previous inode through a hard link, reload the new JSON, and list remaining sibling files. This uses the same candidate file store, independently of controller failure injection. |
| `reopen` | Construct a fresh controller from the original initial state, then load the real saved file and remount if needed |
| `restore` | Reopen the real saved JSON through the controller |
| `switch_actor` | `actor`, optional `platform`, optional `mount`: reopen the component around its current state with a trusted constructor identity |
| `capture` | `name`: distinct PNG basename; export the real rendered widget tree |
| `mutate_initial` | Clear the caller's retained constructor input to check isolation |
| `mutate_snapshot` | Clear a returned snapshot to check isolation |
| `mutate_screens` | Edit a returned title/platform list to check isolation |
| `mutate_saved_argument` | Clear the store's retained save argument to check isolation |

Each observation contains its operation name, actual controller state/error/busy flag, successful file write count, and mounted widget text/keys and text grouped under each keyed subtree. `act` also contains `accepted` and whether the action object remained unchanged. Rejected business actions remain valid observations (`accepted=false`/`error`); adapter or render failures make the public command fail. PNGs and the independently reopened final `persisted_state` accompany observations. Tests must assert the required business behavior, not merely command completion.

You can add ordinary `flutter_test` tests in your own project and run `flutter test --no-pub`. Preserve the published application interfaces and widget keys. The generic adapter is read-only; all expected values used by hidden evaluation remain outside the candidate process.
