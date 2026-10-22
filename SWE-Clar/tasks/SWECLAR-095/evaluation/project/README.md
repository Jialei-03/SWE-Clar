# Listening library repair

An independently authored React web application, Python HTTP service and SQLite store. The source commission explicitly prioritizes the website; this task selects its account/payment/catalog/playback component. No client code, content or payment account is supplied. React 18.3.1, esbuild 0.25.0, Node 22, Python 3.11+. The prepared environment already supplies these dependencies through UI_NODE_MODULES. Run `node build.mjs`, then `python demo.py`; no package download is needed. The demo creates fresh local payment fixtures and synthesized audio in temporary storage. All purchasing here is local, without a real charge.

Service configuration: STREAM_CONFIG, STREAM_DATABASE, STREAM_ASSETS. Config contains provider, api_key, receipt_key and catalog:[{id,title,artist,cost,filename}]. Provider API: authenticated GET /accounts?email=..., POST /accounts {email}, GET /receipts/{id}. A receipt is {payload:{transaction_id,payment_id,status,tokens},signature}; signature uses HMAC-SHA256 over sorted compact JSON. Client API: POST /register and /login {email,password}; GET /me,/catalog?q=...,/licenses,/media/{id}; POST /credit {transaction_id},/license {track},/logout {}. Use Authorization: Bearer with the returned local session token. Protocol details, token prices and demo identities are synthetic benchmark conventions.

Repair the existing app rather than substituting JSON playback states. The actual media adapter uses browser audio. ClearKey/CENC DRM, native React Native players, production AWS/payment webhooks and complete OWASP/accessibility certification remain outside the verified component and require separate review. Local authorization is not a DRM implementation. The catalog search ordering is a benchmark convention; no verified source locator specifies that exact order. Native platform scope and later playback changes are not inferred from this web component.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
