# Realtime mobile notifications and cart

Repair this Flutter mobile UI and Node.js realtime backend. The Flutter project contains a notification inbox, channel controls, product list and cart. HttpShopApi uses actual HTTP and WebSocket connections. Start the backend with SHOP_CONFIG pointing to an external synthetic JSON fixture (users,sessions,products) and run `node server/server.cjs`; it prints its loopback port. Products use integer price_cents. Configure Flutter with API_BASE and ACCESS_TOKEN via dart-define.

The backend supports GET /catalog, /inbox and /cart; POST /actions; and an authenticated WebSocket at /events. Actions are subscribe/unsubscribe(channel), publish(id,channel,title), add/remove(product_id,quantity). Bearer sessions determine the user; caller user IDs are not trusted. The initial project already loads records over HTTP but its push display and cart behavior need repair. Clarify delivery, replay, validation and pricing requirements as needed.

Use Flutter 3.47.2/Dart 3.13.2 and Node.js with ws 8.19.0. This independently reconstructed Flutter and realtime-service component uses a normalized Node backend instead of the private Laravel/Vue services. It does not claim OS push delivery, Android/iOS device testing, the original screens or production persistence. All identities, products and messages are synthetic.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
