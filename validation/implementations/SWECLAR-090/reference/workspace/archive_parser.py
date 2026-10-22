"""HTML archive parsing for the archive-to-PDF package.

The archive format used by this project is deliberately small: records are
marked with the ``archive-entry`` class and carry their identity and date in
``data-*`` attributes.  This module uses the standard library parser rather
than regular expressions so that nested markup and character references are
handled in the same way as ordinary HTML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import re
from typing import Any


class ArchiveError(ValueError):
    """Raised when the supplied document is not a valid archive."""


@dataclass
class _Node:
    """A small HTML tree node used only while parsing an archive."""

    tag: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node"] = field(default_factory=list)
    text: str = ""


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_IGNORED_TAGS = {"script", "style"}
# These elements introduce visible separation in normal HTML rendering.  A
# separator is added at their boundaries, then all whitespace is normalized.
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
_WHITESPACE_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class _TreeBuilder(HTMLParser):
    """Build just enough of a tolerant HTML tree for archive extraction."""

    def __init__(self) -> None:
        # convert_charrefs performs one normal HTML character-reference
        # decoding pass.  In particular, ``&amp;lt;`` correctly remains
        # ``&lt;`` rather than being decoded twice later on.
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag=None)
        self._stack: list[_Node] = [self.root]

    @staticmethod
    def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in attrs:
            # HTMLParser lower-cases attribute names.  The last value is the
            # useful interpretation for the malformed duplicate-attribute
            # case, and is also what browsers expose in most DOM APIs.
            result[key.lower()] = "" if value is None else value
        return result

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = _Node(tag=tag, attrs=self._attributes(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag.lower(), attrs=self._attributes(attrs))
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        # HTML is commonly not perfectly balanced.  Close the nearest open
        # matching element, discarding any implicitly closed descendants.
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(_Node(text=data))

    def handle_comment(self, data: str) -> None:  # pragma: no cover - explicit documentation of intent
        # Comments are not visible article text.
        return

    def handle_decl(self, decl: str) -> None:  # pragma: no cover - no tree node is needed
        return



def _normalize_text(value: str) -> str:
    """Collapse HTML-visible whitespace without performing double unescaping."""

    return _WHITESPACE_RE.sub(" ", value).strip()



def _visible_text(node: _Node) -> str:
    """Return descendant text visible to a reader of the HTML document."""

    pieces: list[str] = []

    def visit(current: _Node) -> None:
        if current.tag is None:
            pieces.append(current.text)
            return
        if current.tag in _IGNORED_TAGS:
            return

        if current.tag == "br" or current.tag in _BLOCK_TAGS:
            pieces.append(" ")
        for child in current.children:
            visit(child)
        if current.tag == "br" or current.tag in _BLOCK_TAGS:
            pieces.append(" ")

    visit(node)
    return _normalize_text("".join(pieces))



def _descendants(node: _Node):
    for child in node.children:
        if child.tag is not None:
            yield child
            yield from _descendants(child)



def _first_descendant(node: _Node, predicate):
    if predicate(node):
        return node
    for child in _descendants(node):
        if predicate(child):
            return child
    return None



def _strict_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ArchiveError("article date is missing or not text")
    value = value.strip()
    if not _ISO_DATE_RE.fullmatch(value):
        raise ArchiveError("article date is not ISO formatted")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ArchiveError("article date is not a calendar date") from exc
    return parsed.isoformat()



def _class_tokens(value: str) -> set[str]:
    return {token for token in value.split() if token}



def parse_archive(text: str) -> list[dict[str, str]]:
    """Parse and validate all article records from raw archive HTML.

    The returned records are normalized but are not filtered by a date range;
    validation intentionally happens before filtering so a malformed record
    cannot be hidden by a caller's selection parameters.
    """

    if not isinstance(text, str):
        raise ArchiveError("archive response is not text")

    parser = _TreeBuilder()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # HTMLParser is tolerant, but expose a stable domain error.
        raise ArchiveError("archive HTML could not be parsed") from exc

    entries: list[_Node] = []

    def collect(node: _Node) -> None:
        if node.tag is not None:
            classes = _class_tokens(node.attrs.get("class", ""))
            if "archive-entry" in classes:
                entries.append(node)
        for child in node.children:
            if child.tag is not None:
                collect(child)

    collect(parser.root)

    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        article_id = entry.attrs.get("data-id", "").strip()
        if not article_id:
            raise ArchiveError("article ID is missing")
        if article_id in seen_ids:
            raise ArchiveError("article IDs are not unique")
        seen_ids.add(article_id)

        article_date = _strict_date(entry.attrs.get("data-date"))

        # The disclosed archive schema supplies publication as an attribute.
        # Treating a missing/blank value as malformed is preferable to silently
        # creating a record whose publication cannot be represented in the PDF.
        publication = _normalize_text(entry.attrs.get("data-publication", ""))
        if not publication:
            raise ArchiveError("article publication is missing")

        title_node = _first_descendant(
            entry, lambda node: node.tag == "h2"
        )
        body_node = _first_descendant(
            entry,
            lambda node: node.attrs.get("data-field", "").strip().casefold() == "body",
        )
        summary_node = _first_descendant(
            entry,
            lambda node: node.attrs.get("data-field", "").strip().casefold() == "summary",
        )

        title = _visible_text(title_node) if title_node is not None else ""
        body = _visible_text(body_node) if body_node is not None else ""
        if not title:
            raise ArchiveError("article title is missing")
        if body_node is None or not body:
            raise ArchiveError("article body is missing")

        record = {
            "id": article_id,
            "date": article_date,
            "publication": publication,
            "title": title,
            "body": body,
        }
        if summary_node is not None:
            summary = _visible_text(summary_node)
            if summary:
                record["summary"] = summary
        records.append(record)

    return records


__all__ = ["ArchiveError", "parse_archive"]
