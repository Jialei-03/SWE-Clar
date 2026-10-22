# Capture desk

Complete this independently reconstructed multi-source video viewer. It has real framed RGB capture over loopback TCP, image transformation/PNG output, a browser canvas preview, device selection, output resolution settings and a virtual-controller input adapter. Finish the preferred-source policy, control behavior and failure presentation after clarification. Preserve working capture and resolution regressions. A changing state label cannot replace actual decoded frames or display-input switching.

This synthetic capture/display exercise uses benchmark-owned loopback interfaces. It does not claim compatibility with physical capture devices or proprietary applications. All source names, pixels, protocols and exact policies are invented benchmark materials. No original camera footage, customer application, hardware identifier, SDK, account or attachment is needed.

## Prepared execution

The benchmark provides Python 3.12, its standard library, SQLite, and Playwright/Chromium in a fixed Linux AMD64 image. No additional image library or download is needed. From `/workspace`, run `python server.py --port 8000 --db /tmp/capture.sqlite`, then visit `http://127.0.0.1:8000`. The default command starts an independent synthetic source thread for development. The manager can instead supply `--camera-port <prepared TCP port>` to use its own source fixture. Port `0` chooses a free HTTP port, printed as a JSON line.

Public tests: `python -I /public_tests/test_public.py`. The benchmark prepares and checks networking, HTTP, browser and storage before the attempt. CPU/memory limits are 2 CPUs, 2 GiB RAM and 256 processes; workspace allowance 512 MiB; evaluation limit 240 seconds. Fresh database paths reset saved settings; reconnecting/restarting the source is managed by the benchmark fixture. Preserve command-line arguments and HTTP/UI hooks; internal structure may change.

## Running pipeline and public interfaces

`synthetic_source.py` supplies moving RGB patterns for two preview devices and a separate auxiliary display input. `wire.py` handles framed requests/responses; `pixels.py` performs image operations; `control.py` holds application policy; `server.py` supplies HTTP/SQLite; `viewer.js` displays actual PNG frames and handles browser/virtual-controller events. The auxiliary input is a second real frame stream, not a CSS label on the preview image.

`GET /api/state` returns `{devices,selected,resolution,zoom,display_input,kiosk,last_action}`. A device is `{id,name,preferred}`. Before discovery: no devices/selection, resolution `640x480`, zoom 1, display input `preview`, kiosk false, last_action null. Discovery runs on startup and through `POST /api/scan` with `{}`. The preferred-source and rescan policy is available through clarification.

`POST /api/control` accepts one JSON event, returning updated state:

| Event type | Fields |
|---|---|
| `device` | `id` from current discovery |
| `resolution` | `value`: `640x480`, `1280x720` or `1920x1080` |
| `display` | `value`: `preview` or `auxiliary` |
| `key` | `key`: a keyboard code string |
| `controller` | `button`: an integer button ID |

Changing resolution must change the actual image/canvas dimensions, not only the reported setting. Reject any other resolution. `GET /api/frame` captures a new frame from the currently chosen display input and returns an actual PNG with `X-Frame-Sequence` (source sequence) and `X-Display-Input` headers. Preview requires a selected source; no selection returns HTTP 409 with `error:no_device`. Source/protocol failures return HTTP 502; invalid control events return HTTP 400, both with `{error:<code>}`. Unknown HTTP routes return 404. Images are uncached. The precise zoom, keyboard/controller effects, source-error recovery and persistent settings are client policies.

Keyboard codes and virtual button inputs enter the same control API. Real DOM keyboard events are supported; for the prepared virtual controller, dispatch `new CustomEvent('controller-input',{detail:{button:0}})` on `window`, or use the provided controller buttons. This explicit input adapter does not pretend to discover physical gamepads. The browser must apply successful display state and continue requesting frames; failed frames must follow the client's presentation policy. Do not solve capture failures by installing a driver or changing dependencies.

## Source wire format

Each TCP connection carries one request and response. Requests are a four-byte unsigned big-endian JSON byte length, then UTF-8 JSON (2–4096 bytes). Requests are `{op:"list"}`, `{op:"frame",input:"preview",device_id:<id>}`, or `{op:"frame",input:"auxiliary"}`. The peer may fragment any part; receive complete fields/payloads. A per-operation source timeout of 1.5 seconds is available in the scaffold. Do not retry against a public network or customer service.

A list response starts with ASCII `LST1`, a four-byte big-endian payload length (2–65536), then a JSON list of at most 32 devices. Each record has exactly `id,name,preferred`. IDs are unique ASCII letters/digits/underscore/hyphen, 1–40 characters; names 1–80 characters; preferred is boolean. A frame response starts with ASCII `FRM1`, then big-endian fields: sequence `uint32`, width `uint16`, height `uint16`, payload length `uint32`, then packed row-major 8-bit RGB with no padding. Width 8–320, height 8–240, payload length exactly `width*height*3`. Sequence is source metadata, not a timestamp invented by the viewer. Invalid lengths, magic, dimensions or incomplete payloads are source failures.

For output, enlarge/stretch the current centered crop to the requested dimensions using nearest-neighbor samples. At zoom `z`, crop dimensions are `floor(source_width/z),floor(source_height/z)`; origin is `floor((source_size-crop_size)/2)` per axis. Output pixel `(x,y)` samples source `(left+floor(x*crop_width/output_width),top+floor(y*crop_height/output_height))`. This public image geometry prevents codec/interpolation choices from becoming an accidental hidden requirement. The client specifies allowed zoom levels and control transitions.

## UI hooks

Preserve `#scan`, `#device`, `#resolution`, `#display-input`, `#controller`, `[data-button]`, `#controls`, `#monitor`, `#video` and `#status`. The canvas reflects decoded image dimensions. Kiosk mode uses the application layout and requires no privileged browser-fullscreen request. Display source names and errors as text. The manager can test both actual DOM input and HTTP events without supplying hidden tests or original history to the coding agent.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
