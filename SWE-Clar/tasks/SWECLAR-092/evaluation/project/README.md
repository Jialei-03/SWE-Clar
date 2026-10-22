# Fleet dashboard workspace

This independently reconstructed HTML/CSS/JavaScript project uses vendored Bootstrap 5.3.3 (MIT). Open `index.html` directly; no build step or remote service is needed. `data.js` supplies synthetic fleet JSON as `window.FLEET_DATA`, with `summary`, `drivers`, and `vehicles` collections. An embedding application can set that global before loading the page. Driver and vehicle records have `id` and `name` fields.

Preserve the existing overview, data rendering, local assets and controls while completing the responsive layout and interactions. `window.dashboard.render()` refreshes the view and `window.dashboard.dispatch(action)` is the local interaction entry point; both operate on the supplied data. The page is a synthetic layout substitute. The unavailable original Figma is not included and pixel equivalence to it is not asserted.

This page excludes a global header/navigation sidebar. The existing Drivers/Vehicles detail panel is local to this component. Preserve the existing control IDs and data entry point. Exact responsive and interaction rules are provided in the task requirements.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
