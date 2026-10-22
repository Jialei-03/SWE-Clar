# Supplied signal component

Independent Python function, JSON CLI and small HTTP/SVG viewer. Implement `evaluate_indicator(config, context)` in solution.py; keep input objects unchanged. Determinism applies to required business fields; additional metadata is allowed. No original Pine code, live data, financial calculation or trade execution is included. The original grade logic was sequence-sensitive; this two-trend classification and exact-string blackout are deliberately simplified local conventions.

Prepared python-web supplies Python3.12.3 and protected browser checks use Playwright/Chromium. No installation or build is needed. CLI: `python cli.py` reads `{config,context}` JSON on stdin and writes a result object. Start `PORT=8080 python server.py`; stdout reports a JSON port. Open http://127.0.0.1:8080/; GET / is health, POST /evaluate carries the same JSON input. Public check: `python /public_tests/smoke.py`. Reload resets local viewer state. Loopback only, 2 CPUs, 2GiB RAM, 256 processes, 256MiB workspace.

Config fields: `triggers` name-to-boolean map, `tf2_enabled`, `blackout_enabled`, `blackout_times` array of strings, `menu_visible`. Context fields: `trigger_states` name-to-boolean map, `htf1` and `htf2` supplied bull/bear observations (null/missing means unavailable), `time` string and `viewport_width` number. Trigger membership is independent and follows context key order. Disabled or absent trigger controls cannot fire. TF1 is the primary enabled timeframe; TF2 is selected separately. Ask the synthetic client for classification, blackout and presentation rules.

Result fields used by adapters: `active_signals` string array, `tf1_active` boolean, `classification` string, `labels_visible` boolean, `styles` containing htf1/htf2/regression CSS color strings, `menu:{visible:boolean,size:string}`. The existing viewer renders labels from the actual active list and line strokes/menu from the result. Its straight lines are intentionally illustrative synthetic geometry, not a reconstructed indicator calculation. Show information menu changes config.menu_visible; viewport_width is supplied from the actual browser width. Invalid adapter requests may use any HTTP4xx error wording; successful responses may include extra metadata.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
