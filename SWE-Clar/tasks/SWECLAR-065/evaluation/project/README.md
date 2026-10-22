# React responsive dashboard

This independently reconstructed React 18.3.1 project has a working dashboard shell and supplied-data rendering. Open index.html locally; all React assets are vendored with their MIT licenses, and no build step or remote request is required. Complete the responsive styles and action handling in app.js. The page should show real metric cards and section content, not return a layout label.

The evaluator supplies window.DASHBOARD_DATA before page load with metrics (named numeric values or numeric arrays) and onboarding_steps (text). window.dashboard.dispatch(action) is the component action adapter and snapshot() exposes a copy of current state. Actions and input data must remain unchanged. Tests use actual DOM layout, clicks and displayed output. The layout and local adapter are reconstruction choices; no original design, customer code or patient record is included. This component does not claim a complete Ionic app or clinical backend.

Use prepared python-web: Python3.12.3 and Playwright/Chromium are installed. No package installation is required. Start `python /workspace/dev_runtime/server.py` to serve the workspace at http://127.0.0.1:8080/ (GET / is the health check). Build: none; public test: `python /public_tests/smoke.py`. Logs are standard HTTP access logs on stderr. All data is synthetic and page-local; reload resets state. The benchmark runs loopback-only, 2 CPUs, 2GiB RAM, 256 processes and 256MiB workspace.

Existing scalar cards, initial numeric validation and SVG chart rendering are public regression context. Complete mobile one-column layout and action dispatch for the existing buttons. Synthetic action types are set_metrics, navigate, start_onboarding and advance_onboarding; ask the synthetic client about precise behavior. Additional state/result metadata and alternative wording for unspecified errors are allowed. Invalid action results have a nonempty error.code. Exact patient screen, breakpoint and interaction specifications are reconstruction conventions, not clinical or customer requirements. No claims submission work is included.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
