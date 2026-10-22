"""Parse one synthetic listing HTML document.

The fixture pages intentionally use ordinary HTML rather than a site-specific
DOM.  This module therefore builds a small tree with :class:`HTMLParser` and
extracts only the elements described by the listing interface.
"""

from html.parser import HTMLParser
import math
import re
from urllib.parse import urljoin


_LABEL_FIELDS = {
    "property type": "property_type",
    "max persons": "max_persons",
    "contact name": "contact_name",
    "latitude": "lat",
    "longitude": "lng",
    "pool": "pool",
}

_OUTPUT_FIELDS = (
    "title",
    "property_type",
    "address",
    "max_persons",
    "contact_name",
    "contact_phone",
    "url",
    "lat",
    "lng",
    "pool",
)

_IGNORED_TAGS = {"script", "style"}
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

_WHITESPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or ())
        self.children = []


class _DocumentParser(HTMLParser):
    """Build enough of an HTML tree for semantic listing extraction."""

    def __init__(self):
        # HTMLParser decodes character references in both text and attributes
        # when convert_charrefs is enabled, which is what the fixture contract
        # requires.
        super().__init__(convert_charrefs=True)
        self.root = _Node("__root__")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        self._add_element(tag, attrs, push=tag.lower() not in _VOID_TAGS)

    def handle_startendtag(self, tag, attrs):
        self._add_element(tag, attrs, push=False)

    def _add_element(self, tag, attrs, push):
        node = _Node(tag.lower(), attrs)
        self._stack[-1].children.append(node)
        if push:
            self._stack.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        # Be tolerant of a missing or mismatched closing tag while still
        # allowing a later sibling to be parsed at the right level.
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if data:
            self._stack[-1].children.append(data)


def _iter_nodes(node):
    """Yield element descendants, excluding script/style subtrees."""

    for child in node.children:
        if not isinstance(child, _Node):
            continue
        if child.tag in _IGNORED_TAGS:
            continue
        yield child
        yield from _iter_nodes(child)


def _text_content(node):
    """Return visible descendant text with HTML whitespace collapsed."""

    pieces = []

    def collect(current):
        for child in current.children:
            if isinstance(child, str):
                pieces.append(child)
                continue
            if child.tag in _IGNORED_TAGS:
                continue
            # A line break contributes visible separation even though it has
            # no text node of its own.
            if child.tag == "br":
                pieces.append(" ")
            collect(child)

    collect(node)
    return _WHITESPACE_RE.sub(" ", "".join(pieces)).strip()


def _normalise_label(value):
    value = _WHITESPACE_RE.sub(" ", value).strip().casefold()
    return value.rstrip(":").strip()


def _element_children(node):
    return [child for child in node.children if isinstance(child, _Node)]


def _descendants_with_tag(node, tag):
    return [child for child in _iter_nodes(node) if child.tag == tag]


def _set_field(record, field, value):
    # If more than one supported layout is present, prefer the first actual
    # value while still allowing an empty earlier element to be completed.
    if record[field] == "" and value != "":
        record[field] = value


def _parse_integer(value):
    match = _NUMBER_RE.search(value)
    if match is None:
        return ""
    token = match.group(0)
    try:
        number = float(token)
    except ValueError:
        return ""
    if not math.isfinite(number) or not number.is_integer():
        return ""
    return int(number)


def _parse_number(value):
    match = _NUMBER_RE.search(value)
    if match is None:
        return ""
    try:
        number = float(match.group(0))
    except ValueError:
        return ""
    return number if math.isfinite(number) else ""


def _coerce_field(field, value):
    if field == "max_persons":
        return _parse_integer(value)
    if field in {"lat", "lng"}:
        return _parse_number(value)
    return value


def _extract_definition_lists(root, record):
    for definition_list in _descendants_with_tag(root, "dl"):
        pending_labels = []
        # dt and dd are normally direct children of dl.  Looking through a
        # harmless wrapper also handles the common generated form with a div
        # around each pair; nested dl elements are uncommon and harmless here.
        for item in _iter_nodes(definition_list):
            if item.tag == "dt":
                label = _LABEL_FIELDS.get(_normalise_label(_text_content(item)))
                if label is not None:
                    pending_labels.append(label)
            elif item.tag == "dd" and pending_labels:
                value_text = _text_content(item)
                for field in pending_labels:
                    _set_field(record, field, _coerce_field(field, value_text))
                pending_labels = []


def _extract_tables(root, record):
    for row in _descendants_with_tag(root, "tr"):
        cells = [child for child in _element_children(row) if child.tag in {"th", "td"}]
        if len(cells) < 2:
            continue

        label_cell = None
        value_cell = None
        for index, cell in enumerate(cells[:-1]):
            if cell.tag == "th" and cells[index + 1].tag == "td":
                label_cell, value_cell = cell, cells[index + 1]
                break

        # Being liberal here costs nothing and supports a two-column table
        # whose first column uses td rather than th.
        if label_cell is None:
            label_cell, value_cell = cells[0], cells[1]

        field = _LABEL_FIELDS.get(_normalise_label(_text_content(label_cell)))
        if field is not None:
            value_text = _text_content(value_cell)
            _set_field(record, field, _coerce_field(field, value_text))


def _canonical_url(root, source_url):
    for node in _descendants_with_tag(root, "link"):
        rel = node.attrs.get("rel", "") or ""
        rel_tokens = rel.split()
        if not any(token.casefold() == "canonical" for token in rel_tokens):
            continue
        href = node.attrs.get("href")
        if href:
            return urljoin(source_url, href)
    return source_url


def _telephone_text(root):
    phones = []
    for node in _descendants_with_tag(root, "a"):
        href = node.attrs.get("href", "") or ""
        if not href.casefold().startswith("tel:"):
            continue
        text = _text_content(node)
        if text:
            phones.append(text)
    return ", ".join(phones)


def parse_listing(html, source_url):
    """Parse one listing document into an intermediate normalized record."""

    parser = _DocumentParser()
    parser.feed(html)
    parser.close()
    root = parser.root

    record = {field: "" for field in _OUTPUT_FIELDS}
    record["url"] = _canonical_url(root, source_url)

    for node in _iter_nodes(root):
        if node.tag == "h1":
            record["title"] = _text_content(node)
            break

    for node in _iter_nodes(root):
        if node.tag == "address":
            record["address"] = _text_content(node)
            break

    _extract_definition_lists(root, record)
    _extract_tables(root, record)
    record["contact_phone"] = _telephone_text(root)
    return record
