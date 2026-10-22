# React Native interaction component

This independently authored project uses React 18.3.1 and React Native Web 0.19.13 to render React Native View, Pressable, ScrollView, Image and PanResponder components in a browser. The benchmark preinstalls the pinned packages in the shared python-practice environment. UI_NODE_MODULES and ESBUILD_BINARY_PATH are already set; do not install dependencies. From /workspace run node build.mjs runtime/dist, then python -m http.server 8080 --bind 127.0.0.1 --directory runtime/dist. Generated build output belongs in runtime/ and is excluded from the code submission.

Repair navigation and the supplied field interactions without replacing the rendered application with a JSON-only simulation. config.json supplies a synthetic route list, protected routes, a host-provided authentication boolean, rating and generated images. This boolean is a fixture for the navigation guard, not a real sign-in or authorization service. Preserve immutable transitions in model.js. The home screen contains a filter, rating and draggable radius control; profile contains a facility image picker and separate account avatar. Image selection uses an actual browser file input adapter; input records alone do not establish image decoding or rendering.

This is a web-executed React Native UI component, not the complete original application or a verified Expo/iOS/Android distribution. Native navigation packages, device image pickers and native gesture behavior require separate platform validation. Route names, facility terminology, synthetic art and schema are reconstruction choices. No original app names, customer assets or customer source code are included.

## Public integration contract

Keep `transition(state, event, config)` exported from `model.js`. State contains `route`, `openNow`, and `error`; preserve unrelated state fields. Navigation events contain `type: "navigate"` and `route`; filter events use `type: "toggle_filter"`. Config contains `routes`, `protectedRoutes`, `authenticated`, `rating`, `placeName`, `facilityImage`, and `accountImage`. The renderer reads config.json at startup. Unknown and unauthenticated protected navigation retain the active route and report `unknown_route` and `auth_required` respectively.

The build command produces `app.js`, `model.cjs`, `index.html`, and `config.json` in its output directory. Keep the existing browser automation hooks (`testID` in React Native Web or `data-testid` in HTML). These identify controls, not a required component implementation:

| Hooks | Purpose |
|---|---|
| `tab-<route>`, `screen-<route>` | Navigation controls and rendered screens |
| `unknown-route`, `route-error` | Missing-route action and feedback |
| `content-scroll` | Actual vertical scroll container |
| `filter-label`, `filter-box` | Filter label/checkbox interaction targets |
| `rating` | Displayed numeric rating |
| `slider`, `slider-thumb`, `slider-value` | Draggable control, thumb and numeric radius |
| `image-picker`, `facility-image`, `account-image`, `image-error` | File input, rendered images and feedback |

Image hooks may identify an img element or a container containing one. Keep the filter's checked state accessible. Layout, internal helper names, state management and image decoding APIs may differ. Specific interaction policies can be clarified with the client.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
