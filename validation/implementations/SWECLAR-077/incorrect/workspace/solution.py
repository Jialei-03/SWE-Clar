"""Reference implementation for the local site/document workflow."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from document_converter import convert_pdf


_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_REGISTRIES = ("assets", "pages", "pdfs", "letterheads", "documents")


def _valid_id(value: Any) -> bool:
    """Whether a value is a permitted filename-safe identifier."""

    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _failed(state: Any, code: str) -> dict:
    """Return the prescribed error result without changing ``state``."""

    # The public adapter supplies a JSON object.  Keeping this defensive makes
    # malformed calls an error result rather than allowing an implementation
    # exception to mutate or partially process anything.
    try:
        result = deepcopy(state)
    except Exception:
        result = {}
    if not isinstance(result, dict):
        result = {}
    result.pop("result", None)
    result["error"] = {"code": code}
    return result


def _source_file(source_root: str | os.PathLike[str], registered_path: Any) -> Path:
    """Resolve a registered path, requiring it to remain under source_root."""

    if not isinstance(registered_path, str):
        raise ValueError("source path must be a string")

    base = Path(source_root).resolve()
    path = (base / registered_path).resolve()
    # ``is_relative_to`` compares resolved path components, so ../ escapes and
    # symlinks which point outside the fixture root are both rejected.
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("invalid source path")
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    """Write bytes with replacement semantics and no partial target file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(path.parent), prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _is_png(data: bytes) -> bool:
    """Perform the small amount of PNG validation needed by the page path."""

    # The source contract requires registered PNG bytes.  Checking the PNG
    # signature and basic chunk framing avoids accepting a renamed text file,
    # without imposing image dimensions or re-encoding the supplied bytes.
    if not data.startswith(_PNG_SIGNATURE):
        return False
    position = len(_PNG_SIGNATURE)
    saw_ihdr = False
    saw_iend = False
    length = len(data)
    try:
        while position + 12 <= length:
            chunk_length = int.from_bytes(data[position : position + 4], "big")
            chunk_end = position + 12 + chunk_length
            if chunk_end > length:
                return False
            chunk_type = data[position + 4 : position + 8]
            if chunk_type == b"IHDR":
                if saw_ihdr or chunk_length != 13:
                    return False
                saw_ihdr = True
            elif chunk_type == b"IEND":
                if chunk_length != 0:
                    return False
                saw_iend = True
                # PNG data after IEND is not needed for this local asset and
                # is treated as malformed rather than silently served.
                return saw_ihdr and chunk_end == length
            position = chunk_end
        return False
    except (OverflowError, ValueError):
        return False


def _valid_viewport_width(value: Any) -> bool:
    # bool is an int subclass, so it must be excluded explicitly.  JSON can
    # carry NaN/Infinity in some Python callers even though they are not valid
    # JSON; reject both rather than making a layout decision for them.
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value > 0
    except (OverflowError, TypeError):
        return False


def _prepare_registries(result: dict) -> bool:
    """Add absent registries on a success candidate and validate their shape."""

    for name in _REGISTRIES:
        if name not in result:
            result[name] = {}
        if not isinstance(result[name], dict):
            return False
    return True


def _page_candidate(state: dict, action: dict, source_root: Any) -> tuple[dict, str] | None:
    """Validate an upsert and return its serialisable page plus page id."""

    page_id = action.get("page_id")
    title = action.get("title")
    body = action.get("body")
    # An omitted section or asset list represents an empty list, matching the
    # page action's natural create-page defaults.
    sections = action.get("sections", [])
    asset_ids = action.get("asset_ids", [])
    viewport_width = action.get("viewport_width")

    if (
        not _valid_id(page_id)
        or not isinstance(title, str)
        or not isinstance(body, str)
        or not isinstance(sections, list)
        or not all(isinstance(section, str) for section in sections)
        or not isinstance(asset_ids, list)
        or not all(_valid_id(asset_id) for asset_id in asset_ids)
        or not _valid_viewport_width(viewport_width)
    ):
        return None

    assets = state["assets"]
    images: list[dict[str, str]] = []
    try:
        for asset_id in asset_ids:
            if asset_id not in assets or not isinstance(assets[asset_id], dict):
                return None
            registered = assets[asset_id].get("path")
            image_path = _source_file(source_root, registered)
            image_data = image_path.read_bytes()
            if not _is_png(image_data):
                return None
            images.append(
                {
                    "id": asset_id,
                    "data": "data:image/png;base64," + base64.b64encode(image_data).decode("ascii"),
                }
            )
    except (OSError, ValueError, TypeError):
        return None

    # Updating a page changes the supplied content fields, but retains existing
    # page metadata (including SEO and any future page-level fields).  A fresh
    # dictionary is used so neither the caller's state nor nested values are
    # changed.
    old_page = state["pages"].get(page_id)
    if old_page is None:
        page: dict[str, Any] = {}
    elif isinstance(old_page, dict):
        page = deepcopy(old_page)
    else:
        return None

    page.update(
        {
            "title": title,
            "body": body,
            "sections": deepcopy(sections),
            "asset_ids": deepcopy(asset_ids),
            "images": images,
        }
    )
    return page, page_id


def process_site_action(state, action, output_root, source_root) -> dict:
    """Apply one local site/document action and return a new state.

    Every branch validates and reads all inputs before its one atomic output
    write.  Consequently an invalid or failed action leaves both the caller's
    state and any previous target file untouched.
    """

    if not isinstance(state, dict):
        return _failed(state, "unknown_action")
    if not isinstance(action, dict):
        return _failed(state, "unknown_action")

    action_type = action.get("type")
    if not isinstance(action_type, str) or action_type not in (
        "upsert_page",
        "set_seo",
        "convert_pdf",
    ):
        return _failed(state, "unknown_action")

    try:
        original = deepcopy(state)
        result = deepcopy(state)
    except Exception:
        return _failed(state, "unknown_action")

    # Failure results intentionally retain the original state shape.  Only the
    # success candidate gets missing registry defaults.
    if not _prepare_registries(result):
        code = {
            "upsert_page": "invalid_page",
            "set_seo": "invalid_seo",
            "convert_pdf": "invalid_document",
        }[action_type]
        return _failed(original, code)

    if action_type == "upsert_page":
        page_result = _page_candidate(result, action, source_root)
        if page_result is None:
            return _failed(original, "invalid_page")
        try:
            output_base = Path(output_root).resolve()
        except (OSError, TypeError, ValueError, RuntimeError):
            return _failed(original, "write_failed")
        page, page_id = page_result
        target = output_base / f"{page_id}.json"
        try:
            payload = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _atomic_write(target, payload)
        except (OSError, TypeError, ValueError):
            return _failed(original, "write_failed")

        result["pages"][page_id] = page
        result.pop("result", None)
        result.pop("error", None)
        result["result"] = {"page_id": page_id, "file": f"{page_id}.json"}
        return result

    if action_type == "set_seo":
        page_id = action.get("page_id")
        title = action.get("title")
        description = action.get("description")
        canonical_path = action.get("canonical_path")
        if (
            not _valid_id(page_id)
            or page_id not in result["pages"]
            or not isinstance(result["pages"].get(page_id), dict)
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(description, str)
            or not description.strip()
            or not isinstance(canonical_path, str)
            or not canonical_path.startswith("/")
            or canonical_path.startswith("//")
            or "\\" in canonical_path
            or "\n" in canonical_path
            or "\r" in canonical_path
        ):
            return _failed(original, "invalid_seo")

        # Preserve the supplied surrounding whitespace in SEO fields.  The
        # non-empty validation above remains in place, but the persisted
        # metadata is intentionally not normalised.
        seo = {
            "title": title,
            "description": description,
            "canonical_path": canonical_path,
            "indexable": True,
        }
        page = deepcopy(result["pages"][page_id])
        page["seo"] = seo
        try:
            output_base = Path(output_root).resolve()
        except (OSError, TypeError, ValueError, RuntimeError):
            return _failed(original, "write_failed")
        target = output_base / f"{page_id}.json"
        try:
            payload = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _atomic_write(target, payload)
        except (OSError, TypeError, ValueError):
            return _failed(original, "write_failed")

        result["pages"][page_id] = page
        result.pop("result", None)
        result.pop("error", None)
        result["result"] = deepcopy(seo)
        return result

    # convert_pdf
    document_id = action.get("document_id")
    pdf_id = action.get("pdf_id")
    letterhead_id = action.get("letterhead_id")
    pdf_entry = result["pdfs"].get(pdf_id) if _valid_id(pdf_id) else None
    letterhead_entry = (
        result["letterheads"].get(letterhead_id) if _valid_id(letterhead_id) else None
    )
    try:
        output_base = Path(output_root).resolve()
    except (OSError, TypeError, ValueError, RuntimeError):
        return _failed(original, "invalid_document")
    target = output_base / f"{document_id}.docx" if _valid_id(document_id) else None

    if (
        not _valid_id(document_id)
        or document_id in result["documents"]
        or target is None
        or os.path.lexists(str(target))
        or not isinstance(pdf_entry, dict)
        or pdf_entry.get("type") != "pdf"
        or not isinstance(letterhead_entry, dict)
    ):
        return _failed(original, "invalid_document")

    try:
        pdf_path = _source_file(source_root, pdf_entry.get("path"))
        letterhead_path = _source_file(source_root, letterhead_entry.get("path"))
        # Conversion returns a complete in-memory document.  No output target
        # is created until all PDF/template validation has succeeded.
        document_bytes = convert_pdf(pdf_path, letterhead_path)
        _atomic_write(target, document_bytes)
    except Exception:
        # Conversion libraries expose several exception classes; all are local
        # input/write failures and must have the same atomic public result.
        return _failed(original, "invalid_document")

    document = {
        "file": f"{document_id}.docx",
        "letterhead_id": letterhead_id,
        "editable": True,
    }
    result["documents"][document_id] = document
    result.pop("result", None)
    result.pop("error", None)
    result["result"] = deepcopy(document)
    return result
