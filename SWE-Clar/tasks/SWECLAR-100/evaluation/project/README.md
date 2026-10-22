# Tablet catalogue web component

Independent Python/SQLite and browser project for a bilingual tablet catalogue. Start with KIOSK_CONFIG=config.json KIOSK_DATABASE=catalogue.sqlite python server.py. The private runtime configuration supplies tokens:{token:{id,role}}, assets:{asset_id:absolute_svg_path} and a loopback settings_url. Roles are device, editor and admin. Use independent synthetic SVG artwork; original product images, branding and device credentials are excluded.

The working HTTP shell, authentication adapter, database schema and page renderer are supplied. Complete editing, publishing and browser synchronization. POST /edit accepts kind (categories/products) and record. Records have id,order,text:{en,es}; products also have category_id,asset_id. POST /publish accepts change_id. GET /snapshot returns version,categories,products,assets with each asset's url and SHA-256. GET /asset/id returns its actual image. The browser should display ordered translated text and actual images, with usable navigation and a retained local content bundle. Tokens are entered at runtime and never placed in the content bundle.

POST /track accepts event_id,target_type,target_id; GET /analytics is restricted to editors/admins. POST /settings accepts device_id and calls the supplied managed-device bridge. The bridge contract is POST {device_id,operation:"open_network_settings"} and reply {device_id,opened:true}. This is a tested connector boundary, not an implementation of Android device-owner APIs or Wi-Fi changes. The task covers the catalogue web component and actual local HTTP transport; it does not claim an Android kiosk lock, Firebase/Rowy deployment, tablet fleet rollout or analytics SaaS account. SQLite schema, English/Spanish fixtures and sync version identifiers are disclosed reconstruction choices.

Offline reload includes the supplied service-worker application shell. Synchronization must persist all validated images and snapshot together; a failed sync or changed access session retains prior content. Logo on a product opens its category; Back restores previous page. Labels (including controls) use selected English/Spanish. These are reconstruction conventions.

For a local synthetic configuration, run `python /workspace/dev_runtime/start.py` from the project directory. The launcher prints the local URL and demonstration tokens; no real device or account is used.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
