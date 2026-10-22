# Responsive PHP content site and document intake

Repair this local PHP website and its Python content/document workflow. The existing PHP page reads generated content JSON from DATA_ROOT and renders actual HTML with supplied text and images. `process_site_action(state,action,output_root,source_root)` manages page updates, SEO and PDF intake without network requests or changing caller objects. Run `DATA_ROOT=/path/to/output php -S 127.0.0.1:8000 -t web`, then open `/index.php?page=home`.

The Python adapter receives state.assets IDs mapped to PNG paths, state.pdfs IDs mapped to {type,path}, and state.letterheads IDs mapped to DOCX template paths under source_root. Page fields are page_id,title,body,sections (ordered strings),asset_ids and viewport_width. Identifier filenames use ASCII letters,digits,underscore and hyphen. Python dependencies are pypdf 6.10.0 and python-docx 1.2.0; PHP 8.3 serves the site. The evaluator uses synthetic images, PDFs and letterheads.

This independently reconstructed content/document component is not the customer's WordPress project or a reproduction of original page design. Text PDFs are used for editable document intake; OCR, complex tables, exact original PDF layout and live hosting are outside this component. Clarify SEO, template handling and error behavior as needed.


This bounded module combines site/logo work, SEO troubleshooting and later editable-letterhead requests from separate stages of the engagement; they are not represented as one original milestone. Exact grid breakpoints, canonical-path policy, line extraction order and atomic error behavior are synthetic benchmark conventions.

The prepared workspace installs PHP, Chromium/Playwright, pypdf, python-docx and Pillow before the task budget. Preflight creates synthetic PNG/PDF/DOCX fixtures and a sample page under `runtime/`. Run `DATA_ROOT=runtime/output php -S 127.0.0.1:8080 -t web` and open `/index.php?page=home`. Run `python /public_tests/test_public.py` for the existing local page/data regression. Runtime files are Git-ignored and excluded from delivery; stop the server and remove `runtime/` then run the protected preflight to reset. No customer logo, template, document or code is included. Two CPUs, 2 GiB RAM, 256 processes; no external network.

Additional result/state metadata is permitted. Tests compare observable content and actual files rather than ZIP bytes or volatile document properties. PNG assets are local synthetic fixtures. DOCX letterhead content includes the body and header; output body paragraphs remain editable text. The supplied error result shape is preserved.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
