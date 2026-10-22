# Classroom audio and session service

Repair the supplied Python session service, local speech adapter and translation connector. `process_class_action(state,action,transcriber=None,translator=None)` is an internal immutable boundary. `python cli.py --db state.sqlite --assets audio-directory init|show|act` initializes once, inspects trusted local state, or reads one action from stdin and atomically saves successful state changes. act prints only result/error. State.users maps synthetic user IDs to teacher/student roles; actor_id is supplied by a trusted application adapter. This CLI is not a public authentication service.

Actions include create_class(class_id,code), join(code), start/pause/resume/complete(class_id,clock), question_click(class_id,question_id,elapsed), question_submit(class_id,question_id,text), transcribe(class_id,segment_id,audio_path,elapsed), feedback, post_class_view, add_material and translate. Audio paths are relative to the isolated asset directory. The supplied transcriber interface must read actual audio; caller text is not a transcription.

Runtime: whisper.cpp 1.7.6, its public ggml tiny.en model, Python 3.12. Set WHISPER_BIN, WHISPER_MODEL and optional TRANSLATION_URL. Evaluator audio is independently synthesized English speech, 16 kHz mono PCM WAV, at most 30 seconds per segment; no classroom recording is distributed. The public model and tool are runtime dependencies, not customer assets. Translation uses a local synthetic HTTP provider during tests.

This reconstructs the audio/session backend component, not the original classroom application UI, production speech service, cloud accounts or live microphone capture. Local English transcription is actually exercised; accuracy in noisy classrooms and other languages is not claimed. Timer clocks and clicked elapsed values are application-supplied fixture values.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
