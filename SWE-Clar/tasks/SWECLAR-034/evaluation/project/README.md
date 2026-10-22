# Listing scraper workspace

This reconstructed Python project fetches HTML and exposes `scrape(urls)` in `solution.py`. Complete `listing_parser.py` and `transform(rows)`; preserve the existing HTTP fetcher and CLI (`python solution.py < urls.json`). Use Python 3.11 or later, standard library only.

The two synthetic examples show equivalent document layouts. A page has a title heading (`h1`), an `address`, and labelled properties in either `dl` / `dt` / `dd` or a table with `th` / `td`. Supported labels are Property type, Max persons, Contact name, Latitude, Longitude, and Pool. Phone values are the visible text of `a` links whose href starts with `tel:`. An optional `link rel="canonical"` contains an explicit URL; the requested URL is the source URI. Resolve a relative canonical URL against the source URI. Ignore scripts, styles, and unrelated sections. Decode HTML entities and collapse whitespace. Max persons is an integer; latitude and longitude are numbers when present. Preserve input URL order and fetch each supplied page. All acceptance pages are served by a synthetic loopback HTTP fixture; no live property site or account is needed.

The final field list is supplied by the initial task interface. Output conventions may need clarification. These fixtures and source files were independently constructed and do not contain customer website code.

Work in `/workspace` in the prepared standard-library Python environment. Run `python /public_tests/test_public.py` for HTTP-reader, fixture and empty-input CLI regression checks. No package installation or external website credentials are required. The benchmark verifies local HTTP and parser capabilities before the coding budget. To run your scraper, supply a JSON array of the fixture URLs on standard input: `python solution.py < urls.json`. Successful output is a JSON array on stdout; failures are reported on stderr. Each call is independent and no database or reset operation is needed. Empty URL lists are supported by the starter; nonempty parsing and normalization remain to implement.
For HTML scraping, pool retains the normalized textual label value (for example yes or no); do not convert it to a boolean. An absent pool is the empty string. This does not change direct transform; it preserves the supplied value and type for non-URL/non-phone fields.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
