# Browser radio component
Run `python server.py` (PORT defaults to 8765), then visit http://127.0.0.1:8765. Run `python /public_tests/smoke.py` for a real Chromium/audio smoke check. No npm installation or external service is required.

The existing project fetches schedule/recent JSON over HTTP and plays synthetic WAV recordings using one HTML audio element. A linear station uses `/api/live` to get a current offset into a 90-second synthetic programme; playing/resuming a station must catch up to that offset (within 1 second). This is a finite local linear-programme simulation, not HLS or a radio hardware certification. Recent programmes start at zero. Keep selection on pause, remove its playing highlight, and replace the old source when selecting another programme.

Keep these public DOM interfaces: `#schedule`, `#recent` with `[data-id]` buttons; `#audio`; `#selected`; `#pause`, `#resume`; `#refresh-schedule`, `#refresh-recent`; timer `#seconds`, `#set-timer`, `#cancel-timer`, `#show-timer`, `#remaining`. The `playing` CSS class identifies the active item. HTTP list rows have id, title, artist, album, live, url. Page refresh replaces only the relevant page from its latest HTTP response. Sleep timers accept positive finite seconds, use elapsed monotonic time, pause at expiry, remain unchanged when displaying remaining time, and cancel completely.

Repair paused highlighting and complete the browser Media Session integration. Ask the client which programme metadata must be published and how selection changes should replace it. Preserve existing functionality. Native CarPlay, Apple APIs, background operation, acoustic output and hardware integration are outside this reconstruction.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
