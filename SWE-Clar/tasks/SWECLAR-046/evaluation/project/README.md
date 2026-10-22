# Source synchronization and outreach connector

Complete the supplied Python data-layer project and PipelineClient HTTP adapter. `process_pipeline_event(state,event,service=None)` preserves caller objects and returns a new state/report. The client is configured with source_urls, destination_urls, outreach_url and optional Bearer token kept outside returned state. Source and destination data must be read from the actual configured services; caller-supplied rows or accepted flags are not proof of remote execution.

The evaluator provides local synthetic HTTP endpoints. The project reconstructs an ETL and outbound-queue integration component; it does not reproduce a private Make workspace, vendor-native API, contact database or live outreach campaign. Transport acknowledgement means the local connector accepted the intent, not that a real person received a message. Clarify preservation rules, eligible channels, acknowledgement and accounting behavior as needed.

## Prepared local environment

Use `/workspace` in `python-web`. Python, SQLite and HTTP libraries are ready before the task; no installation or real credentials are needed. Limits: 2 CPU, 2048 MiB memory, 256 processes, 256 MiB workspace. Networking is local loopback only.

- Sample: `python cli.py < example.json`.
- Public checks: `python /public_tests/test_public.py`.
- Reset: `python -c "import shutil; shutil.rmtree('runtime', ignore_errors=True)"`.

The console reads `{"state": ..., "event": ...}`, automatically starts the local provider, configures the client with temporary authentication and prints the result. The provider loads synthetic `source.json` and persists destination/queue rows in `runtime/provider.db`; `--database PATH` selects another file. It stops automatically; there is no external delivery. Errors appear on stderr. Keep runtime databases out of code delivery.

The provided GET adapters work. Implement `PipelineClient.upsert`, `PipelineClient.submit_outreach` and the workflow. Preserve the console and local service. Auth tokens must remain inside transport configuration. Caller state is explicitly supplied each invocation; remote destination and queued deliveries persist in the provider database.

## Public data contract

State is a JSON object with optional `sources` and `destinations` mappings, `runs` list, `outbox` list and unrelated metadata. Missing collections start empty. A destination entry is a mapping of normalized source IDs to record objects. Source rows contain `source_id` and arbitrary data fields. Service responses are authoritative; cached caller data may be stale. Extra nonconflicting output metadata is allowed.

Events are `sync(source,destination,run_id?)` or `queue_outreach(destination,source_id,channel,run_id?)`. Named endpoints refer to the configured client mappings. Explicit `run_id` must be a nonempty string and is validated before HTTP requests; when absent use `run:<completed run count + 1>`. Return `result` and append the same run summary to `runs`, with `run_id`, `processed`, `created`, `updated`, `skipped`, `failed`. Each attempted source row increments processed; each operation outcome increments one outcome counter. An outreach request processes one row. Successful operations clear stale error/result fields. Errors contain `error.code`; malformed run IDs use `invalid_run_id`, malformed or unavailable service reads use `service_failed`.

`PipelineClient` methods are `read_source(name)`, `read_destination(name)`, `upsert(destination,source_id,row)`, `submit_outreach(delivery_id,email)`. The source GET returns a JSON array; destination GET returns an object keyed by ID, with object-valued rows. PUT to `destination_url/<percent-encoded ID>` sends the full record and returns `{"accepted":true,"source_id":"..."}`. POST to outreach URL sends `{"delivery_id":"...","email":"..."}` and returns `{"accepted":true,"delivery_id":"..."}`. See the client for transport configuration and header support; ask the client simulator for business ownership, queue eligibility and retry rules.

A failed or mismatched write acknowledgement must not update the local confirmed cache or success count. A remote write can already have occurred when its acknowledgement is lost; retry uses the same row/delivery identifier rather than claiming remote rollback. The prepared queue provides idempotent acceptance and never sends external messages.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
