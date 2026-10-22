# Rolling level analyzer

Implement `analyze_levels` in `levels.py` while preserving the supplied JSON console. This is a standalone calculation task over synthetic OHLC bars, not a trading platform, broker integration or investment recommendation.

Use `/workspace` and prepared `python-web`: Python and standard-library tools are ready, no installation or internet needed. Limits: 2 CPU, 2048 MiB memory, 256 processes, 256 MiB workspace.

- Run a file: `python cli.py example.json`.
- Run stdin: `python cli.py < example.json`.
- Public check: `python /public_tests/test_public.py`.
- Reset: no persistent state; each invocation is independent. Errors appear on stderr.

Input has `bars`, `lookback` and optional `options` matching the function's keyword parameters. Each bar contains finite numeric `open`, `high`, `low`, `close`, with low ≤ open/close ≤ high. Booleans are not prices. Lookback is a positive integer; an empty history or history no longer than lookback produces no levels. Options `use_close_instead_of_wick`, `keep_past_levels`, `hide_broken_levels` are booleans; `min_distance_ticks` is a nonnegative integer, `tick_size` a positive finite number, `extend_points` a nonnegative integer. Invalid input raises ValueError. Preserve inputs and make no network or interactive calls.

Output contains lists `active_levels`, `display_levels` and `break_events`. A level has `side` (high/low), `price`, `created_at` (zero-based bar index), `status` (active/broken/replaced), `extends_to`. Break events contain `side`, `price`, `index`. Additional nonconflicting metadata is permitted. Return records in creation order, high before low at the same index; break events in chronological order, then level creation order. Numeric int/float equivalents are acceptable; no particular internal algorithm is required.

Calculate candidates from exactly the preceding lookback bars, excluding the current bar. Ask the client about retention, replacement, spacing suppression and break/display behavior. The console is provided and runnable; the starter intentionally does not compute levels yet.

The break-event output key is exactly `index`, the zero-based breaking bar index. `bar_index` is not a replacement for `index`. Clarification must preserve this output name; the requirement's phrase “bar index” describes the value, not a different JSON field.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
