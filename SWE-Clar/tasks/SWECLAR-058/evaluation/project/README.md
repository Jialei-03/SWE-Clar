# Local voice room

Complete the participant, speaking-turn and audio behavior in `solution.py` while preserving room creation, the HTTP service and browser controls. This independently constructed application uses synthetic participants and a generated tone. It requires no microphone, customer account, Unity installation or external provider.

The prepared Python 3.12.3 environment supplies all dependencies; no package installation is required. Build: `python -m compileall -q .`. Public regression: `python /public_tests/smoke.py`. Work in `/workspace`; start with `python server.py --port 8080` and open `http://127.0.0.1:8080/`. `/health` checks the server. Restart it to reset all rooms and queued audio. Two browser tabs can represent two participants. Use **Receive audio**, then the audio player's play control, to hear received packets. Errors are displayed in the page status area.

`process_voice_event(state, event)` returns a new state with `result` or `error.code`, preserving both inputs. Alternative nonempty error codes and additional metadata are allowed. Initial state has `admins` and a `rooms` mapping. A successful room creation returns `result.room_id`. Invalid actions preserve existing room data. HTTP `POST /events` returns 200 on success and 400 on failure; malformed requests must not stop the server.

Events use `type`, `room_id` and, where relevant, `user_id`. Available operations are `create_room(admin_id,private,access_token,turn_limit)`, `join(access_token)`, `lock_pass`, `unlock_pass`, `advance`, `pass`, `timeout`, and `audio(packet_id,audio_base64)`. Time-dependent operations provide finite numeric `server_time` in seconds; the browser supplies its local clock. This is a deterministic local demonstration, not a production identity or trusted-clock system.

Rooms are created only by IDs in `state.admins`, have unique nonempty IDs and a positive finite turn limit. Private rooms require a nonempty string token. Booleans are not numeric limits or timestamps. Existing room creation works; ask the synthetic client about joining, locked turns, deadlines, replay and delivery rules.

Audio input is base64-encoded WAV containing nonempty mono signed 16-bit PCM at 8000 Hz, at most 1 MiB of decoded data. `/demo.wav` supplies a generated 250 ms tone. An accepted audio result provides `packet_id`, `audio_base64` containing the unchanged audio bytes, and a `recipients` list. The server delivers these actual bytes into each selected participant inbox. `GET /inbox?room_id=...&user_id=...` drains that inbox and returns `packets` with `packet_id` and `audio_base64`; the browser decodes the data into real audio players. Metadata without audio content cannot fulfill delivery.

Limits: 2 CPU, 2048 MiB memory, 256 processes, 256 MiB workspace; execution network is loopback only. The runtime provides dependencies and an independent environment preflight before the agent budget. This bounded task covers local turn-based audio delivery; production voice codecs, encryption, device capture and Internet conferencing are outside its scope.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
