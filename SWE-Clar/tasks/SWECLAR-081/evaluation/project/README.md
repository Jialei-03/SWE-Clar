# Offline directory page planner
Implement `directory_planner.py: plan_directory_update(records, changed_ids, query=None, immediate_ids=None)` without mutating inputs. Return pages, suggestions and cache_queue; metadata is permitted. Invalid inputs raise ValueError. This component generates real local page content and work plans, not a complete directory site or external CDN deployment.

Record fields: unique nonempty string id, business_name,country_code,state_name,state_code,main_city; other_cities/services lists of nonempty strings; sponsored boolean. Empty lists/record collection allowed. changed_ids and optional immediate_ids are lists of known IDs; repeated IDs allowed. query string or None. Exact route normalization and refresh policies may be clarified.

Generate state, state_service, city, city_service and business pages. Both main and other cities contribute; every offered service contributes at state/city levels. Deduplicate equivalent normalized cities/services and business memberships. Page fields: route,kind,label,business_ids. Labels: state+' Movers', state+' '+service+' Movers', city+' '+state_code+' Movers', city+' '+state_code+' '+service+' Movers', business_name. For normalized equivalent labels choose lexicographically smallest trimmed label. Sponsored businesses sort first, then ID; pages sort by route.

Search normalized ASCII text across all page labels, including businesses. Exact/prefix/substring scores are300/200/100; sort by descending score then route; at most10 unique target routes. Each suggestion exposes target,kind,label,score. Empty normalized query yields none. Token normalization uses NFKD ASCII transliteration, lowercase alphanumeric runs with single spaces.

Run `python cli.py --offset 0 --limit 20` with one JSON object containing function arguments on stdin. offset>=0,limit>=1. Only pages paginate; total_pages is full count and suggestions/cache_queue remain complete. CLI produces actual escaped HTML containing page heading and matching business names in membership order. It writes JSON to stdout and publishes nothing. Python standard library only.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
