"""Local PDF-to-DOCX conversion helpers.

The workflow deliberately handles only text PDFs.  A DOCX letterhead is opened
as the base document and extracted PDF lines are appended as ordinary Word
paragraphs, so the result remains editable and the template is not recreated
(or accidentally duplicated) by the converter.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class DocumentConversionError(ValueError):
    """Raised when a local input cannot be converted by this workflow."""


def _pdf_lines(source: Path) -> list[str]:
    """Return non-empty extracted PDF lines in page/line order.

    The benchmark inputs are text PDFs with an unambiguous reading order.  We
    intentionally do not attempt OCR, image extraction, or layout
    reconstruction here.  ``pypdf`` is used on the registered file itself so
    callers cannot supply pre-extracted blocks in its place.
    """

    try:
        reader = PdfReader(str(source))
    except Exception as exc:  # malformed, unsupported, or unreadable PDF
        raise DocumentConversionError("unsupported PDF") from exc

    # Accessing pages on an encrypted reader raises in pypdf.  Reject it before
    # doing so rather than attempting to guess or use a password.
    try:
        if reader.is_encrypted:
            raise DocumentConversionError("encrypted PDF")
    except DocumentConversionError:
        raise
    except Exception as exc:
        raise DocumentConversionError("unsupported PDF") from exc

    lines: list[str] = []
    try:
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            # splitlines handles the line endings emitted by pypdf.  Strip
            # only surrounding whitespace: internal spacing is document text,
            # and repeated lines are intentionally not deduplicated.
            for line in text.splitlines():
                line = line.strip()
                if line:
                    lines.append(line)
    except DocumentConversionError:
        raise
    except Exception as exc:
        raise DocumentConversionError("unsupported PDF") from exc

    if not lines:
        raise DocumentConversionError("PDF contains no text")
    return lines


def _clear_personal_metadata(document: Document) -> None:
    """Remove personal authoring fields from a generated document."""

    properties = document.core_properties
    # These are the author-identifying fields exposed by python-docx.  Empty
    # values are serialised without retaining the template's personal names.
    properties.author = ""
    properties.last_modified_by = ""
    properties.comments = ""


def convert_pdf(source: str | Path, template: str | Path) -> bytes:
    """Convert a local text PDF into an editable DOCX based on ``template``.

    The supplied DOCX is loaded once and kept as the output document.  Its
    body, headers, styles, and other content therefore occur exactly once;
    extracted PDF lines are appended as normal editable body paragraphs.
    """

    source_path = Path(source)
    template_path = Path(template)

    # Read and validate all source material before constructing output.  This
    # also makes it explicit that an empty/blank PDF is not a successful
    # conversion.
    lines = _pdf_lines(source_path)
    try:
        document = Document(str(template_path))
    except Exception as exc:  # missing, malformed, or non-DOCX template
        raise DocumentConversionError("unsupported letterhead template") from exc

    for line in lines:
        document.add_paragraph(line)

    _clear_personal_metadata(document)

    stream = BytesIO()
    try:
        document.save(stream)
    except Exception as exc:
        raise DocumentConversionError("could not write DOCX") from exc
    return stream.getvalue()
