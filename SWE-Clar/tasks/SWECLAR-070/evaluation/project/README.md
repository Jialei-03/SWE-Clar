# Roof estimate web component

Independent Python/SQLite/Leaflet 1.9.4 project. Run ROOF_CONFIG=config.json ROOF_DATABASE=roof.sqlite python server.py. Private config contains geocoding_url, solar_url, api_key and pricing:{roof_type:{name:rate},material:{name:rate},extras:{name:rate}}. Benchmark endpoints must be loopback. Provider fixtures follow Google Geocoding and Solar buildingInsights request/response shapes; the evaluator sends only independent synthetic addresses/coordinates.

Complete actual address lookup, validated provider area, map bounds, quote arithmetic and session-scoped enquiry persistence. GET /current returns the current browser session's detection/quote; GET /pricing returns configured example rates. POST /detect accepts address; POST /quote accepts detection_id,roof_type,material,extras; POST /lead accepts lead_id,quote_id,name,email,phone,address. Do not trust supplied area or override authorization fields. Successful quotes use canonical two-decimal strings and reference stored detected data. Anonymous browser sessions are isolated by HttpOnly cookies and persist in SQLite.

The map displays provider building bounds through Leaflet; it does not render original aerial imagery or reconstruct a roof polygon. Solar wholeRoofStats.areaMeters2 describes modelled segments, which may omit parts of a real roof. This benchmark tests API integration and the quoted component, not remote detection accuracy or a complete commercial building survey. No manual-boundary editor is required in this MVP component. Original addresses, leads, maps, API credentials and customer pricing are excluded. Test prices and contact records are synthetic. Leaflet's public license is retained under vendor.


Prepared workspace
------------------
Python, SQLite, Playwright/Chromium and the vendored Leaflet library are installed. The preflight starts a synthetic loopback provider before the task budget and writes `runtime/roof-config.json`. Run:

    ROOF_CONFIG=runtime/roof-config.json ROOF_DATABASE=runtime/roof.sqlite PORT=8080 python server.py

Use `Synthetic address A`. The provider models 120.5 m² and small building bounds around (0.001, 0.002); it makes no external request. Run `python /public_tests/test_public.py` for the existing entry-point regression. Stop the app and delete `runtime/roof.sqlite` to reset saved sessions and records. Runtime files are ignored by Git and excluded from delivery. The evaluator runs offline with 2 CPUs, 2 GiB RAM and 256 processes. Source edits belong in this existing project.

Reconstructed protocol and schema
---------------------------------
The configured HTTP endpoints accept GET query parameters `address` and `key` for geocoding, then `location.latitude`, `location.longitude`, and `key` for Solar. Geocoding responds with `status`, `results`, optional `partial_match`, and each result's `geometry.location.lat/lng`. Solar responds with `center.latitude/longitude`, `boundingBox.sw/ne.latitude/longitude`, and `solarPotential.wholeRoofStats.areaMeters2`. Coordinates are finite geographic numbers and the non-wrapping box has south < north and west < east, containing its centre. Reject ambiguous partial matches. Preserve the submitted address (trimmed), modelled area, centre and bounds; discard unrelated provider fields.

The existing SQLite tables and JSON payload interface remain the integration boundary: detections contain `detection_id,address,area_m2,center,bounds`; quotes contain `quote_id,detection_id,address,area_m2,roof_type,material,extras,items,total`; each item has `kind,name,amount`. Leads retain contact fields, their ID and the stored quote. Additional metadata is allowed. IDs need not be reproducible, and repeated quote requests need not reuse an ID. The provider/schema/pricing fixtures are independent synthetic conventions, not live-service certification. Leaflet bounds show orientation, not an exact roof outline. No API keys, source identities, original imagery or complete commercial platform are included.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
