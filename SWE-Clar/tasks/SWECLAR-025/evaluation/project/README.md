# Inspection records component

Repair this independently authored PHP/SQLite and JavaScript component. Community selection and creation are working regressions; complete deletion and community reporting after clarifying the business rules. The task is this inspection-record module, not a full property-management system or PDF generator.

The shared `php-document` environment provides PHP 8.3, PDO SQLite, Python and Chromium. The benchmark prepares `/workspace/runtime/config.json` before your budget starts. It contains synthetic communities, initial inspections and access codes. Work in `/workspace` and start:

```
INSPECTION_CONFIG=/workspace/runtime/config.json INSPECTION_DB=/workspace/runtime/records.sqlite PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:8000 -t web router.php
```

Open `http://127.0.0.1:8000/`. Development access codes are `demo-admin`, `demo-inspector`, and `demo-office`; they map to the corresponding roles. Stop with Ctrl-C. Restart preserves the database. The benchmark reset restores the starter and gives you fresh runtime storage. Run visible regressions with `python /public_tests/test_public.py`. No external service or credentials are required.

GET `/api/context` and POST `/api/command` use `Authorization: Bearer <access-code>`. Context returns `role`, `communities` (community to street arrays) and `inspections`. Each inspection exposes `id`, `community`, `street`, `residence`, `status`. Commands: `create` takes those address fields and a supplied ID; `delete` takes an ID; `report` takes a community. Creation returns `result.id` and `result.status`; deletion returns `result.deleted`; reports return `result.total` and `result.by_status`. Operation errors use `error.code`. Clarify permission, report, status and error policies with the client.

Preserve accessible form labels and the existing interaction controls. Inspection rows use `data-id` equal to their record ID and the report output uses `id="summary"`; these public browser hooks do not require a particular tag or layout. Internal PHP functions, SQL tables and implementation choices are unrestricted. Fixtures are supplied by the benchmark and must not be changed. Runtime files belong under `/workspace/runtime` and are excluded from the submitted code patch.

All records, communities, residences, code and access codes are synthetic. Original client code, screenshots and documents are not provided. PHP/SQLite, access-code roles and the exact acceptance policies are benchmark conventions.

Accessible controls retain the names `Community`, `Street`, `Residence`, and `Inspection ID`; button names are `Sign in`, `Create inspection`, `Delete`, and `Generate report`. HTML indentation and surrounding whitespace do not change these names. Preserve the existing `access-code` input and `workspace` visibility container. Browser automation locates the Community combobox by its normalized accessible name, not raw label-node whitespace or a required tag layout.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
