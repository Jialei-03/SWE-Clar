# Distance-constrained local routing component

Run `STATE_PATH=state.json GRAPH_URL=http://127.0.0.1:port/network python server.py`. The loopback web service persists one local user's state and renders clickable SVG routes. It is not a public multi-user service. Input routes and off-route distance flags are untrusted: the component must calculate geometry itself.

The graph provider accepts POST {start_node} and returns {nodes:{id:{lat,lon}},edges:[[from,to],...]}. Edges are directed straight road segments. Benchmark networks contain 3–24 nodes, at most 60 edges and coordinates within 20 km of the start. Enumerate unique simple directed loops returning to the start, with 3–10 distinct nodes, at most 100,000 search states, and geodesic lengths within requested_miles ± tolerance. Select and display real geometry, not arbitrary nearby shortest routes. Edge distance labels are ignored. Local point-to-segment distance is used for navigation checks. This disclosed synthetic network is a small routing benchmark, not a city-wide road database or a production directions provider.

`process_navigation_action(state,action,client=None)` preserves inputs. Actions: generate_alternatives(start_node,requested_miles,tolerance), place_point(lat,lon), select_route(route_id), start_navigation, progress(event_id,position,threshold_meters), set_theme(theme). The graph HTTP adapter and UI shell are supplied; repair incomplete route generation and navigation behavior. Only successful actions are atomically persisted. Coordinates describe synthetic geometry, never customer addresses or GPS histories. Background GPS and native vibration are not validated; alerts carry an intent for a downstream device adapter.

Route IDs must be stable for an identical directed node sequence, independent of input edge order; no exact hash or spelling is prescribed. A loop contains its start once plus 2–9 other distinct nodes, followed by the start again in its geometry. Repeated edges do not create alternatives. A traversal state is a visited simple path beginning at the start (including that initial path); abort atomically before visiting state 100001. Local projection for each segment uses the current position as origin: x=R*cos(position latitude)*radians(longitude difference), y=R*radians(latitude difference), followed by the closest point on the closed segment. These constants, enumeration budget and exact policies are reconstruction conventions.

The prepared Python web environment includes the browser runtime; public fixtures provide a local synthetic HTTP graph service. Run `python /workspace/dev_runtime/start.py` from the workspace and open its printed URL. The server and graph provider stay loopback-only; runtime state is excluded from exports.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
