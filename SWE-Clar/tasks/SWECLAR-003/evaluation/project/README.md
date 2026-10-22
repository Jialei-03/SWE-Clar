# Local campaign site builder

Complete this independent Python/HTML/CSS/JavaScript static-site project. It must build an actual responsive page with local images, campaign cards, contact form, consent controls and footer links. Clarify content/asset handling, consent precedence and local request rules with the client. Original customer code, branding and images are not included.

## Prepared environment and commands

The benchmark provides Python 3.12 and Chromium with its browser test tools in a Linux AMD64 container. No download, dependency installation or external account is needed. CPU: 2; memory: 2 GB; writable workspace: 512 MB; temporary storage: 1 GB. Only loopback networking is available. Use regular source and output files, without symlinks.

```sh
python solution.py site assets < spec.json
python -m http.server 8000 --bind 127.0.0.1 --directory site
python -I /public_tests/test_public.py
```

Open `http://127.0.0.1:8000` after starting the local server. Rebuild to update the generated files. The dedicated `site` output directory is disposable; source files and input assets remain elsewhere. Evaluation supplies fresh, disjoint output and asset directories. Application data is stored locally in the browser; no messages are sent to another person or service.

Keep `build_campaign_site(spec, output_dir, asset_root)` in `solution.py` and the command-line entry above. The function returns `{"index_file":"index.html"}` on success, or `{"error":{"code":"invalid_spec"}}` / `{"error":{"code":"invalid_asset"}}` for invalid input. The CLI reads one JSON object from stdin and prints the returned object as JSON. Build bytes must be repeatable for the same input and assets; do not mutate the supplied dictionary. Invalid field shape is checked before asset resolution. Manager-provided output paths refer to dedicated writable directories, not source/assets or filesystem roots.

## Input interface

All fields below are required except `consent_decision`. No additional fields are accepted. String content is preserved literally; names/title/description are nonblank, not executable markup.

| Field | Shape |
|---|---|
| site_id | `[a-z][a-z0-9-]{0,39}` |
| locale | `[a-z]{2}(-[A-Z]{2})?` |
| title | nonblank string, at most 160 characters |
| description | nonblank string, at most 600 characters |
| hero_asset | local image filename |
| available_assets | array of distinct string filenames |
| campaigns | 1–12 objects, each exactly `{name,asset}`; name is nonblank and at most 120 characters |
| legal | exactly `{privacy,terms,disclosure}` with distinct local fragment destinations |
| consent_decision | omitted, null, `accept` or `decline` |

An image filename uses `[A-Za-z0-9][A-Za-z0-9._-]{0,79}` followed by `.svg`, `.png`, `.jpg`, `.jpeg` or `.webp`. Input assets are benchmark-owned images with no active code or external resources. Legal destinations use `#[a-z][a-z0-9-]{0,39}`; they cannot be `hero`, `campaigns`, `contact`, `footer`, `consent`, `accept`, `decline`, `form-status`, `outbox-count`, or begin with `campaign-`. Both malformed input and asset-related failures use the result interface above; clarify which assets are required and how a failed rebuild affects an existing output.

## Page interface

Preserve `#hero` with one h1 and its image, `#campaigns` with `.campaign-card` elements (h2 and img), `#contact` with one form, and `#footer` with its three links. Core content must remain within the viewport. Cards use three columns at widths >=1024, two at 600–1023 and one below 600. Card order follows input order; their IDs must be unique and nonempty. Color, font, card spacing and exact pixel heights are flexible.

The form has fields named `name`, `email`, `message`, a submit button, `#form-status` and `#outbox-count`. Status text is `invalid_contact` for invalid submissions and `saved_locally` for a saved local request. Count text is `Requests: N`. Clarify validation, normalization, storage and reset policies rather than assuming browser-default validation is sufficient.

The consent panel is `#consent` with `#accept` and `#decline` buttons. The browser storage interface uses keys `campaign:<site_id>:consent` (a decision string) and `campaign:<site_id>:outbox` (a JSON array). New local request records have exactly `request_id`, `name`, `email`, `message`, all strings. Evaluation observes actual DOM, storage and network behavior; no window function or self-reported success flag is required. Each site ID has its own storage namespace.

All scripts, styles and images must be generated local resources. Each supplied footer destination must resolve to an actual local section; its explanatory wording is free and must remain clearly synthetic. There is no external message submission or tracking. Static-site delivery does not imply a legal-policy or consent-compliance certification.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
