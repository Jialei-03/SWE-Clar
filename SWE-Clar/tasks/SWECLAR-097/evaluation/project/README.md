# Date planning component

Independent Python/SQLite HTTP application with Leaflet 1.9.4 (BSD-2-Clause license included). Start DATE_CONFIG=config.json DATE_DATABASE=dates.sqlite python server.py. Private configuration supplies synthetic users:{id,username,name,salt,password_hash,credits,latitude,longitude} as a list, matches:[{id,name,users:[id,id]}], products:[{id,quantity,amount_minor,currency}], provider_url, provider_token and receipt_key (hexadecimal). Password verifiers use salted hashlib.scrypt with n=16384,r=8,p=1. No fixture contains real profiles, addresses or payment credentials.

Repair actual venue search, selected map geometry, credit consumption and confirmed package purchase. A local provider fixture implements POST /places/search {query}, /places/get {id}, /payments/confirm {id,user,product_id,amount_minor,currency}; requests use a private bearer token. Place responses contain id,name,type,latitude,longitude. Payment responses contain payload and a SHA-256 HMAC signature over UTF-8 canonical JSON (sorted keys, compact separators). Payload adds status to the request fields. These independently designed protocols exercise real HTTP and receipt validation; they are not Apple Pay or Google Places certification. The provider must enforce idempotency of confirmation IDs.

POST /login establishes the cookie session. GET /me returns actor, wallet, matches, products and dates; GET /places?q=text searches venues. POST /credit and /purchase take id,match_id,place_id and optional product_id. Server-side configuration determines price and credit quantity. Public synthetic products are 1, 3 and 5 dates at EUR 10, 27 and 40; these replace source prices and are explicitly benchmark choices.

Only the date planning component is rebuilt, not a complete matching app, native mobile app, production payments or Firebase deployment. Source phrasing disagrees on whether one remaining credit is sufficient; this benchmark explicitly uses at least one as a reconstruction resolution, without claiming direct client confirmation. Map imagery and places are independent synthetic geometry, without original venue names, addresses or geographic traces.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
