"""Public entry point for building an archive article PDF package."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import os
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable

from fetcher import fetch_text as default_fetch_text
from archive_parser import ArchiveError, parse_archive
from pdf_renderer import PDFRenderError, render_pdf


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")



def _error(code: str) -> dict[str, dict[str, str]]:
    # Keep the public error shape small and stable.  In particular, exception
    # messages are intentionally not exposed as they may contain environment
    # paths or remote-server details.
    return {"error": {"code": code}}



def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    if not _ISO_DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None



def _optional_text(params: Mapping[str, Any], names: tuple[str, ...]) -> str | None:
    """Read an optional text filter, accepting a few documented spellings."""

    for name in names:
        if name in params:
            value = params[name]
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError("optional filter is not text")
            value = re.sub(r"\s+", " ", value).strip()
            return value or None
    return None



def _summary_requested(params: Mapping[str, Any]) -> bool:
    # include_summaries is the public spelling.  The two harmless aliases make
    # the entry point tolerant of callers using the singular wording in older
    # examples, while leaving the supplied params mapping untouched.
    for name in ("include_summaries", "include_summary", "summaries"):
        if name in params:
            value = params[name]
            if isinstance(value, str):
                return value.strip().casefold() in {"1", "true", "yes", "on"}
            return bool(value)
    return False



def _safe_filename(title: str, start_date: str, end_date: str) -> str:
    # Transliteration is only for the filename; the returned title and the
    # rendered title retain the caller's text.  Restricting the slug to a
    # conservative ASCII set prevents separators, dot-dot components, and
    # platform-specific special characters from escaping output_dir.
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-._")
    slug = slug[:100].rstrip("-._")
    if not slug:
        slug = "article-package"
    return f"{slug}-{start_date}-{end_date}.pdf"



def _select_articles(
    records: list[dict[str, str]],
    start: date,
    end: date,
    publication: str | None,
    query: str | None,
    include_summaries: bool,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    publication_key = publication.casefold() if publication is not None else None
    query_key = query.casefold() if query is not None else None

    for record in records:
        record_date = date.fromisoformat(record["date"])
        if not (start <= record_date <= end):
            continue
        if publication_key is not None and record["publication"].casefold() != publication_key:
            continue
        if query_key is not None:
            searchable = f"{record['title']} {record['body']}".casefold()
            if query_key not in searchable:
                continue

        article: dict[str, Any] = {
            "id": record["id"],
            "date": record["date"],
            "publication": record["publication"],
            "title": record["title"],
            "body": record["body"],
        }
        if include_summaries:
            if record.get("summary"):
                article["summary"] = record["summary"]
            else:
                article["summary_missing"] = True
        selected.append(article)

    selected[:] = __import__('control_algorithms').stable_order(selected, key=lambda article: (article["date"], article["id"]))
    return selected



def build_article_package(
    params: Mapping[str, Any],
    archive_url: str,
    output_dir: str | os.PathLike[str],
    fetch_text: Callable[[str], str] | None = None,
) -> dict:
    """Fetch, select, normalize, and render an archive article package.

    Validation and archive parsing complete before the renderer is called.  As
    a result, malformed input or malformed archive records cannot create a
    new PDF.  The input mapping itself is read-only from this function's
    perspective.
    """

    # Validate all local inputs before invoking a potentially remote reader.
    if not isinstance(params, Mapping):
        return _error("invalid_input")
    required = ("title", "start_date", "end_date")
    if any(name not in params for name in required):
        return _error("invalid_input")

    title = params["title"]
    start_text = params["start_date"]
    end_text = params["end_date"]
    if not isinstance(title, str) or not title.strip():
        return _error("invalid_input")
    start = _iso_date(start_text)
    end = _iso_date(end_text)
    if start is None or end is None or start > end:
        return _error("invalid_input")

    try:
        publication = _optional_text(
            params, ("publication", "publication_filter", "filter_publication")
        )
        query = _optional_text(params, ("query", "query_filter", "search"))
    except ValueError:
        return _error("invalid_input")

    if fetch_text is not None and not callable(fetch_text):
        return _error("invalid_input")
    if not isinstance(archive_url, str) or not archive_url:
        return _error("invalid_input")
    try:
        # PathLike is accepted without changing the caller's object.  The
        # renderer performs the actual directory creation only after a valid
        # archive and a successfully rendered PDF exist in memory.
        output_path = Path(output_dir)
    except (TypeError, ValueError):
        return _error("invalid_input")

    reader = default_fetch_text if fetch_text is None else fetch_text
    try:
        raw_html = reader(archive_url)
    except Exception:
        return _error("fetch_error")
    if isinstance(raw_html, bytes):
        try:
            raw_html = raw_html.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _error("fetch_error")
    if not isinstance(raw_html, str):
        return _error("fetch_error")

    try:
        records = parse_archive(raw_html)
    except ArchiveError:
        return _error("invalid_archive")
    except Exception:
        return _error("invalid_archive")

    include_summaries = _summary_requested(params)
    articles = _select_articles(
        records, start, end, publication, query, include_summaries
    )
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    filename = _safe_filename(title.strip(), start_iso, end_iso)

    package = {
        "title": title,
        "articles": articles,
        "filename": filename,
        # The renderer uses these values only for deterministic cover text.
        "start_date": start_iso,
        "end_date": end_iso,
        "publication": publication,
        "query": query,
        "include_summaries": include_summaries,
    }
    try:
        render_pdf(package, output_path)
    except PDFRenderError:
        return _error("output_error")
    except Exception:
        return _error("output_error")

    return {"title": title, "articles": articles, "filename": filename}


__all__ = ["build_article_package"]
