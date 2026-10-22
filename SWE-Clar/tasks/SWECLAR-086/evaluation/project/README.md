# Incremental itinerary backend
Implement iter_json_objects and stream_itinerary in itinerary_generator.py, and resolve_activity/is_valid_place in place_service.py. Preserve real streaming through main.py --places local.json --location TEXT. Python standard library only; no live external API.

Upstream is an iterable of string chunks containing adjacent JSON objects, arbitrary whitespace and fragmentation. Objects can contain nested arrays/objects and escaped strings. Yield each completed object before requesting another chunk, preserving order/fields. Ignore an incomplete final object; reject a fully closed malformed JSON object/nonobject prefix/nonstring chunk with ValueError. Empty stream/chunks emit nothing. Six-line formatting is accepted but JSON object boundaries define records, not line count.

An activity contains business_name,description and optional metadata. Resolve using find_place(business_name,location); accepted metadata overrides activity collisions, preserving every other field. Acceptance thresholds/exemptions and replacement rules may be clarified. Local fixture file has primary mapping business_name to place and replacement mapping description to place; callbacks return dictionary or None.

stream_itinerary resolves in order, skips unresolved activities, emits one data: JSON followed by two newlines per acceptable result. JSON spacing/key order is free. CLI must flush an event while stdin is still open; whole-input buffering is incorrect. No external publishing or production provider integration is claimed. Config/openai_client are retained inactive seams; credentials are unnecessary.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
