"""Deterministic, printable PDF rendering for article packages."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


_CONTENT_MARGIN = 20 * mm
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_FOOTER_RESERVE = 18


class PDFRenderError(OSError):
    """Raised when a package cannot be rendered or written."""



def _font_width(text: str, font_name: str, font_size: float) -> float:
    return stringWidth(text, font_name, font_size)



def _split_long_word(word: str, font_name: str, font_size: float, width: float) -> list[str]:
    """Split an unbroken word without dropping any of its characters."""

    if not word:
        return [""]
    pieces: list[str] = []
    current = ""
    for character in word:
        candidate = current + character
        if current and _font_width(candidate, font_name, font_size) > width:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [""]



def _wrap_text(text: str, font_name: str, font_size: float, width: float) -> list[str]:
    """Wrap text by measured font width, retaining every non-space character."""

    # Archive fields have already had HTML whitespace normalized.  Applying
    # the same conservative normalization to the package title also prevents
    # an input newline from becoming an invalid multi-line drawString call.
    words = re.sub(r"\s+", " ", str(text)).strip().split(" ")
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        if _font_width(word, font_name, font_size) > width:
            chunks = _split_long_word(word, font_name, font_size, width)
            if current:
                lines.append(current)
                current = ""
            if chunks:
                lines.extend(chunks[:-1])
                current = chunks[-1]
            continue

        candidate = word if not current else f"{current} {word}"
        if current and _font_width(candidate, font_name, font_size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


class _Paginator:
    """Draw text while keeping a footer and content margins on every page."""

    def __init__(self, pdf: canvas.Canvas) -> None:
        self.pdf = pdf
        self.page_number = 1
        self.cursor = _PAGE_HEIGHT - _CONTENT_MARGIN
        self._page_finished = False

    @property
    def text_x(self) -> float:
        return _CONTENT_MARGIN

    @property
    def text_width(self) -> float:
        return _PAGE_WIDTH - (2 * _CONTENT_MARGIN)

    @property
    def bottom(self) -> float:
        return _CONTENT_MARGIN + _FOOTER_RESERVE

    def _reset_cursor(self) -> None:
        self.cursor = _PAGE_HEIGHT - _CONTENT_MARGIN
        self._page_finished = False

    def finish_page(self) -> None:
        if self._page_finished:
            return
        self.pdf.setFont("Helvetica", 8)
        self.pdf.drawCentredString(_PAGE_WIDTH / 2, _CONTENT_MARGIN, str(self.page_number))
        self._page_finished = True

    def new_page(self) -> None:
        self.finish_page()
        self.pdf.showPage()
        self.page_number += 1
        self._reset_cursor()

    def _ensure_space(self, leading: float) -> None:
        if self.cursor - leading < self.bottom:
            self.new_page()

    def line(
        self,
        text: str,
        *,
        font: str = "Helvetica",
        size: float = 10,
        leading: float | None = None,
        indent: float = 0,
    ) -> None:
        if leading is None:
            leading = size * 1.25
        self._ensure_space(leading)
        baseline = self.cursor - size
        self.pdf.setFont(font, size)
        self.pdf.drawString(self.text_x + indent, baseline, text)
        self.cursor -= leading
        self._page_finished = False

    def wrapped(
        self,
        text: str,
        *,
        font: str = "Helvetica",
        size: float = 10,
        leading: float | None = None,
        indent: float = 0,
        width: float | None = None,
    ) -> None:
        if leading is None:
            leading = size * 1.25
        available = self.text_width - indent if width is None else width
        for line in _wrap_text(text, font, size, available):
            self.line(line, font=font, size=size, leading=leading, indent=indent)

    def spacer(self, amount: float) -> None:
        # A spacer may consume the remainder of a page, but never creates a
        # page merely because an article has just ended.
        if amount <= 0:
            return
        if self.cursor - amount < self.bottom:
            self.new_page()
        else:
            self.cursor -= amount



def _draw_cover(pager: _Paginator, package: dict) -> None:
    pager.wrapped(
        package["title"],
        font="Helvetica-Bold",
        size=24,
        leading=30,
    )
    pager.spacer(20)
    pager.wrapped("Archive article package", font="Helvetica", size=12, leading=16)
    pager.spacer(14)
    pager.wrapped(
        f"Date range: {package['start_date']} to {package['end_date']}",
        size=10,
        leading=14,
    )
    pager.wrapped(f"Articles: {len(package['articles'])}", size=10, leading=14)
    if package.get("publication"):
        pager.wrapped(f"Publication filter: {package['publication']}", size=10, leading=14)
    if package.get("query"):
        pager.wrapped(f"Query filter: {package['query']}", size=10, leading=14)



def _draw_article(pager: _Paginator, article: dict, include_summaries: bool) -> None:
    pager.wrapped(
        article["title"],
        font="Helvetica-Bold",
        size=17,
        leading=22,
    )
    pager.spacer(7)
    pager.wrapped(f"Date: {article['date']}", size=9, leading=12)
    pager.wrapped(f"Publication: {article['publication']}", size=9, leading=12)
    pager.wrapped(f"Article ID: {article['id']}", size=9, leading=12)

    if include_summaries and article.get("summary"):
        pager.spacer(9)
        pager.wrapped("Summary:", font="Helvetica-Bold", size=10, leading=13)
        pager.wrapped(article["summary"], size=10, leading=13, indent=10)

    pager.spacer(10)
    pager.wrapped("Body:", font="Helvetica-Bold", size=10, leading=13)
    pager.wrapped(article["body"], size=10, leading=13)



def _make_pdf_bytes(package: dict) -> bytes:
    stream = BytesIO()
    try:
        # invariant=1 fixes ReportLab's normally time-dependent document
        # metadata and identifier.  Standard Type 1 fonts keep output small
        # and are sufficient for the disclosed fixture character set.
        pdf = canvas.Canvas(
            stream,
            pagesize=A4,
            pageCompression=1,
            invariant=1,
            verbosity=0,
        )
        pdf.setTitle(str(package["title"]))
        pdf.setAuthor("Archive-to-PDF")
        pdf.setCreator("Archive-to-PDF reference renderer")
        pdf.setSubject("Selected archive articles")

        pager = _Paginator(pdf)
        _draw_cover(pager, package)

        articles = package["articles"]
        if articles:
            pager.new_page()
            for index, article in enumerate(articles):
                _draw_article(pager, article, bool(package.get("include_summaries")))
                if index != len(articles) - 1:
                    # Regardless of how much the previous article used, the
                    # next selected article always starts on a fresh page.
                    pager.new_page()

        pager.finish_page()
        pdf.save()
        return stream.getvalue()
    except Exception as exc:
        raise PDFRenderError("could not render PDF") from exc



def _safe_target(output_dir: str | os.PathLike[str], filename: str) -> tuple[Path, Path]:
    directory = Path(output_dir)
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".pdf"):
        raise PDFRenderError("unsafe PDF filename")
    target = directory / filename
    return directory, target



def _atomic_write(directory: Path, target: Path, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise PDFRenderError("output directory is not a directory")

    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(directory)
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except Exception as exc:
        raise PDFRenderError("could not write PDF") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass



def render_pdf(package: dict, output_dir: str | os.PathLike[str]) -> str:
    """Render ``package`` and atomically write its deterministic PDF.

    The return value is the basename written under ``output_dir``.  Rendering
    occurs before the output directory is touched, so a rendering failure
    cannot leave a partially written target file.
    """

    try:
        filename = str(package["filename"])
        directory, target = _safe_target(output_dir, filename)
        data = _make_pdf_bytes(package)
        _atomic_write(directory, target, data)
        return filename
    except PDFRenderError:
        raise
    except Exception as exc:
        raise PDFRenderError("could not write PDF") from exc


__all__ = ["PDFRenderError", "render_pdf"]
