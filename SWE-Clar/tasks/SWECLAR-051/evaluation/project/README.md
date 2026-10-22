# Piano performance batch application

Maintain this independently authored MIDI application. The current code reads and writes genuine Standard MIDI Files and renders an ordinary input through a prepared VST3 instrument. Timing/velocity/articulation policy and robust batch delivery are unfinished. Ask the client about these business choices before implementing them. All project code and musical examples are reconstructed; no customer project, recordings or instrument samples are included.

## Prepared commands

Work in `/workspace`:

```sh
python app.py /tmp/midi-input /tmp/midi-output --seed 0 --articulation normal
python -I /public_tests/test_public.py
python -I /opt/sweclar/preflight.py
```

Create a separate input directory containing your test `.mid` files. The public helper `/public_tests/audio_support.py` can generate a small synthetic MIDI fixture. Use a new output directory to reset a trial. Inspect stderr and the final JSON line on stdout. All writable project files are in `/workspace`; `/tmp` is available for temporary input/output. No package installation or network access is required.

Python 3.11, Mido 1.3.3, the offline host `/opt/sweclar/clar_render`, the synthetic `/opt/sweclar/ClarPiano.vst3` instrument and `/opt/sweclar/render_midi.py` are preinstalled. MIDI parsing and the renderer adapter are available to inspect. The plugin and host remain protected environment components; the task concerns the Python application. Resource ceilings are 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace and 1 GiB temporary storage; writable storage consumes that same memory budget. Commands have a 120-second limit and full evaluation has 240 seconds.

## Input and output interface

`app.py INPUT_DIRECTORY OUTPUT_DIRECTORY [--seed INTEGER] [--articulation normal|staccato]` accepts an unsigned 32-bit seed, default `0`, and articulation `normal` by default. Invalid arguments, a missing input directory, a non-directory output path, or overlapping input/output directory trees must exit `2` before processing or creating outputs, with an explanation on stderr. The two directory trees must be separate.

Supported input is SMF type 0 or 1 with positive PPQN and tempo, 1–10000 positive-duration notes and at most 120 seconds under the source tempo map. Support multiple tracks, polyphonic notes, MIDI channels, tempo changes and note-on velocity zero releases. Pair notes within their original track/channel/pitch. Same-key notes within a track must not overlap. Type 2, SMPTE timing, percussion channel 9, cross-track pairing, unmatched releases and unterminated notes are outside the supported input contract. Repeated same-pitch notes on separate tracks are valid and independent.

Keep file type, track count, PPQN, pitch, channel and note count. Preserve every non-note event at its original absolute tick, including tempo changes and metadata. Equivalent note-off encodings and MIDI serialization are allowed. The exact timing, velocity and articulation changes are client decisions.

For an input relative path `group/phrase.mid`, successful deliverables are regular self-contained files:

```text
OUTPUT_DIRECTORY/group/phrase.mid/performance.mid
OUTPUT_DIRECTORY/group/phrase.mid/render.wav
```

The final stdout line is a JSON object containing `results`, an array of objects with `input` (relative POSIX path), `status` (`ok` or `error`), `error` (`null`, `invalid_midi`, `existing_output` or `render_failed`) and `notes` (integer or `null`). Ask the client about discovery order, recursive directories, failure continuation, existing results, atomic publication and per-file error policy.

## Actual audio delivery

Render the produced `performance.mid`, using its transformed note events and original tempo map, through the prepared host and synthetic instrument. This is real offline VST3 processing, not a playback-status report. The adapter command is:

```sh
python -I /opt/sweclar/render_midi.py performance.mid render.wav
```

WAV output is stereo 16-bit PCM at 44100 Hz. Convert event times from the exact tempo map to the nearest sample frame, rounding half a frame upward and retaining at least one sample of a positive tick-duration note. End at the last quantized note-off plus 22050 release-tail frames; do not extend the result to a trailing end-of-track timestamp. Keep the waveform produced by the supplied instrument. WAV metadata/serialization may vary without changing the PCM signal. No compatibility with commercial instruments or Windows/macOS packaging is claimed.

The host exposes `CLARSWE_AUDIO_RENDER_ERROR=1` as an explicit development fault switch: it exits unsuccessfully without producing a WAV. The ordinary environment leaves it unset. Use it to test external renderer failure handling; ask the client how a failed render affects a batch and any existing outputs.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
