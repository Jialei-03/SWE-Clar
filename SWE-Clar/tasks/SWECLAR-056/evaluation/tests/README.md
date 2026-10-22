# Socket integration tests

The five gates use actual loopback HTTP/WebSocket handshakes and frames. Install Node.js 20+ and ws 8.19.0 in the evaluator environment (or install the pinned task dependency before isolation). Tests and dependency installation are evaluator-owned. Set SWECLAR_PROJECT_DIR and SWECLAR_LOG_DIR, then run the official Python verifier. Missing Node/ws is an infrastructure failure; an implemented service failing protocol checks is a candidate failure.

JWT secrets are generated for the test run. No customer service, credential or device is used. The deterministic injected clock tests timeout boundaries without sleeps. The suite does not certify the original production connection-scale objective.
