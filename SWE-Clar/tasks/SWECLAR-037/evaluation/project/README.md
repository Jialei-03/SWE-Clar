# Video event and clip component

The reconstructed project decodes actual video, detects a synthetic colored target, applies an event policy, cuts the separate recording and sends the actual clip bytes to a configured delivery adapter. Repair the policy and clip pipeline. Run `python cli.py request.json`.

Input JSON fields: detection_video, recording_video, output_dir (must not exist), line_x, delivery_url; optional cooldown_seconds, ffmpeg, ffprobe. Both videos use the same zero-based timeline. Benchmark videos are at most 30 seconds, 640x480 and 60 fps. Public fixtures are independently generated colored shapes. No customer footage, trained detector weights, camera endpoints or messaging accounts are supplied.

The preserved detector uses red-pixel centroids crossing into x >= line_x as its disclosed synthetic target condition. This exercises actual frames, not a supplied recognition flag. It does not establish YOLO quality or performance on real sports footage. The delivery adapter accepts video/mp4 POST with X-Content-SHA256 and X-Clip-ID and returns JSON {accepted:true,sha256:...}; a local test receiver stands in for the external messaging integration.

Complete src/goal_policy.py and pipeline.py. A successful run creates clips and manifest.json. An error leaves no completed output directory; an external recipient may already have accepted earlier clips in a failed multi-clip run. Production delivery retry and multi-camera/live buffering are outside this isolated recorded-video component.

## Prepared local workflow

The benchmark provides FFmpeg/ffprobe, three independently generated videos and a local delivery receiver before coding begins. Python uses only the standard library. From `/workspace`, run `python /public_tests/test_public.py /workspace` for the preserved decoder, empty-event CLI and delivery adapter smoke checks. Try the event example with `python cli.py runtime/request.json`; the incomplete policy/clip branch still requires implementation.

`runtime/request.json` contains actual sample paths and the running receiver URL. `runtime/detection.mp4` contains synthetic red targets, `runtime/neutral.mp4` contains none, and `runtime/recording.mp4` is a synchronized changing-color recording. No external accounts or video downloads are needed. To rerun the example, choose a fresh `output_dir` in a copied request; existing output directories must remain untouched. Runtime assets and outputs are excluded from the source deliverable.

## Output and policy contract

`cooldown_seconds` is a public nonnegative numeric option with default 5.0; ask about suppression timing and boundary behavior. Policy observations contain numeric `timestamp` and boolean `goal_candidate`, with optional extra metadata. The policy returns numeric timestamps and must preserve inputs and avoid application I/O; ordinary prepared standard-library imports are allowed.

CLI output and `manifest.json` each contain a chronological `clips` array. Each record has relative `file`, numeric `trigger`, `start`, `end`, and content `sha256`. These fields must agree between the two outputs; additional harmless metadata is allowed. The codec and output frame rate may differ from the reference provided the MP4 is playable and preserves the required time interval and recording content. Error rejection need not use a particular Python exception class.

The encoded clip duration may differ from the requested interval by at most 0.12 seconds to allow frame/container rounding. Preserve the recording content: for the supplied spatially uniform synthetic recordings, decoded spatial-average RGB values at corresponding interior times may differ by at most 8 per channel on the 0–255 scale. These are public media-fidelity tolerances, not an exact codec or frame-rate requirement.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
