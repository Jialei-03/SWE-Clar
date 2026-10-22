# Archive-to-PDF project

Complete `build_article_package(params, archive_url, output_dir, fetch_text=None)` in solution.py. The supplied HTTP reader retrieves raw HTML; the optional callable(url) adapter returns HTML text. The archive parser and PDF renderer are extension points. Return a dictionary with title, articles and filename, and write the actual PDF under output_dir; failures return error.code. Do not change input parameters. Python 3.11+ and reportlab 4.4.9 are required.

This benchmark's synthetic HTML archive uses article.archive-entry elements with data-id, data-date and data-publication attributes. Each contains an h2 title, an element with data-field="body", and optionally data-field="summary". Extract nested visible text and HTML entities, excluding scripts/styles. Dates are ISO calendar dates. All text fixtures use characters supported by the standard PDF fonts. params requires title, start_date and end_date and may contain publication/query filters. The small example is fictional and contains no client article or account information.

The project evaluates actual HTML ingestion, selection and PDF generation using a local test server. The HTML schema is a disclosed reconstruction choice; it does not reproduce a private publisher's website or claim to bypass live website access controls.

Optional supplied summaries are source fields, not generated AI text. The publication filter matches without case distinctions; query searches visible title and body text. Exact HTML rules and PDF layout/reproducibility policies are independent benchmark conventions, not customer-confirmed publisher specifications. The prepared environment includes rendering dependencies; run `python /public_tests/example.py` for the synthetic example.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
