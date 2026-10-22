# Assistant conversation interface

Repair this independently reconstructed HTML/CSS/JavaScript project. It includes actual page controls, saved conversation records and a browser UI. window.ASSISTANT_DATA supplies synthetic initial data; window.assistantApp.dispatch(event) returns a Promise and snapshot() returns a copy of state. Preserve configured data and caller events. Serve the project over local HTTP; browser storage provides persistence for this component.

Opening an existing conversation must return to its saved transcript and pending question, including after a reload. Keep user text as literal text. All example conversations and routes are synthetic. The task does not include a real model, health records, customer designs or private chat history. Feedback/report delivery is verified through a local test service rather than a real recipient. Further formatting, navigation and reporting behavior can be clarified.

The prepared workspace is `/workspace`. Python, Playwright and Chromium are preinstalled. Start the local interface with `python /workspace/dev_runtime/serve.py --project /workspace --port 8080`; run visible checks with `python /public_tests/test_public.py`. The protected server serves files and a local JSON report receiver. No installation or external network is needed. The environment provides 2 CPUs, 2 GB memory, 256 process slots and a 256 MB workspace. Browser profiles and fixture logs stay outside your deliverable.

Open `http://127.0.0.1:8080` while the server is running. To reset this origin, run `localStorage.removeItem("assistant-workspace"); location.reload()` in the browser console. This removes only this component’s saved workspace.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
