"""Page snapshots, change history, archive lifecycle and subscriptions.

The application deliberately keeps upstream requests outside SQLite write
transactions.  A short commit transaction re-checks all of the state observed
before the request, which makes archive/subscription transitions visible to
slow snapshot requests without holding a database-wide writer lock while the
provider is contacted.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common import (
    Problem,
    fields,
    ident,
    require,
    timestamp,
)
from storage import transaction


# The provider is local, but disabling environment proxies makes the request
# unambiguously an actual request to the configured provider.  This handler
# intentionally does not follow redirects: redirects are not page snapshots or
# canonical receipt responses.
class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_PROVIDER_OPENER = build_opener(ProxyHandler({}), _NoRedirect())

_PAGE_LIMIT = 262144
_RECEIPT_LIMIT = 16384
_PROVIDER_TIMEOUT = 5.0

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
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
    "hr",
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
_EXCLUDED_TAGS = {"head", "script", "style", "template", "noscript"}
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


class _VisibleText(HTMLParser):
    """Collect static visible text according to the workflow's HTML policy.

    HTMLParser supplies decoded character references when ``convert_charrefs``
    is true.  A tag stack is used rather than a single skip flag so void tags in
    a head and malformed-but-common nesting do not leak or hide later text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def _excluded(self) -> bool:
        return any(tag in _EXCLUDED_TAGS for tag in self.stack)

    def _separator(self) -> None:
        self.parts.append(" ")

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401, ANN001
        tag = tag.lower()
        hidden = self._excluded()
        if not hidden and tag in _BLOCK_TAGS:
            self._separator()
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: D401, ANN001
        tag = tag.lower()
        if not self._excluded() and tag in _BLOCK_TAGS:
            self._separator()
            self._separator()

    def handle_endtag(self, tag: str) -> None:  # noqa: D401
        tag = tag.lower()
        was_visible = not self._excluded()
        # HTMLParser does not repair the stack.  Remove through the nearest
        # matching tag, which is a useful approximation for malformed static
        # HTML and keeps exclusion descendants bounded.
        found = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                found = index
                break
        if found is not None:
            del self.stack[found:]
        if was_visible and tag in _BLOCK_TAGS:
            self._separator()

    def handle_data(self, data: str) -> None:  # noqa: D401
        if not self._excluded():
            self.parts.append(data)

    # Comments, declarations and processing instructions deliberately have no
    # handlers that add text.
    def normalized(self) -> str:
        # str.split() uses Unicode whitespace, and joining with a literal space
        # gives the required single ASCII separators and trimming.
        return " ".join("".join(self.parts).split())


def normalize_html(raw: bytes) -> str:
    """Decode and statically extract normalized page text."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Problem(502, "provider_invalid_body") from exc
    if "\x00" in text:
        raise Problem(502, "provider_invalid_body")
    parser = _VisibleText()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # HTMLParser should be forgiving, but body errors are provider errors.
        raise Problem(502, "provider_invalid_body") from exc
    return parser.normalized()


def _content_length(headers, limit: int) -> None:  # noqa: ANN001
    value = headers.get("Content-Length")
    if value is None:
        return
    try:
        length = int(value.strip(), 10)
    except (AttributeError, ValueError) as exc:
        raise Problem(502, "provider_invalid_response") from exc
    if length < 0 or length > limit:
        raise Problem(502, "provider_oversized_response")


def _identity_encoding(headers) -> None:  # noqa: ANN001
    values = headers.get_all("Content-Encoding") or []
    for value in values:
        pieces = [piece.strip().lower() for piece in value.split(",")]
        if any(piece not in ("", "identity") for piece in pieces):
            raise Problem(502, "provider_encoding")


def _media_type(headers, expected: str) -> None:  # noqa: ANN001
    value = headers.get("Content-Type")
    if not isinstance(value, str):
        raise Problem(502, "provider_content_type")
    media = value.split(";", 1)[0].strip().lower()
    if media != expected:
        raise Problem(502, "provider_content_type")


def _read_provider(url: str, limit: int, expected_type: str, not_found: bool = False) -> bytes:
    """GET one provider resource with strict response boundaries."""
    request = Request(url, method="GET", headers={"Accept": expected_type})
    try:
        response = _PROVIDER_OPENER.open(request, timeout=_PROVIDER_TIMEOUT)
    except HTTPError as exc:
        # With _NoRedirect, redirects arrive here too and are intentionally
        # treated like every other unsuccessful provider response.
        try:
            exc.close()
        except Exception:
            pass
        if not_found and exc.code == 404:
            raise Problem(404, "receipt_not_found") from exc
        raise Problem(502, "provider_unavailable") from exc
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise Problem(502, "provider_unavailable") from exc
    except Exception as exc:
        # Network stacks can surface implementation-specific HTTP exceptions
        # (for example an incomplete chunked body).  They are provider
        # failures, never application 500s.
        raise Problem(502, "provider_unavailable") from exc

    try:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if status != 200:
            raise Problem(502, "provider_unavailable")
        _media_type(response.headers, expected_type)
        _identity_encoding(response.headers)
        _content_length(response.headers, limit)
        try:
            raw = response.read(limit + 1)
        except Problem:
            raise
        except Exception as exc:
            raise Problem(502, "provider_unavailable") from exc
        if response.headers.get("Content-Length") is not None and len(raw) != int(response.headers["Content-Length"]):
            raise Problem(502, "provider_truncated_response")
        if len(raw) == 0 or len(raw) > limit:
            raise Problem(502, "provider_oversized_response" if len(raw) > limit else "provider_empty_response")
        return raw
    except Problem:
        raise
    except Exception as exc:
        raise Problem(502, "provider_invalid_response") from exc
    finally:
        try:
            response.close()
        except Exception:
            pass


def _fetch_page(provider: str, url: str) -> tuple[str, str]:
    raw = _read_provider(url, _PAGE_LIMIT, "text/html")
    text = normalize_html(raw)
    # ``hexdigest`` is lowercase; the normalized text itself remains literal
    # and case-sensitive.
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def _fetch_receipt(provider: str, receipt_id: str) -> dict:
    raw = _read_provider(
        provider + "/v1/receipts/" + receipt_id,
        _RECEIPT_LIMIT,
        "application/json",
        not_found=True,
    )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("receipt is not an object")
        if set(value) != {"id", "account_id", "sequence", "plan", "status"}:
            raise ValueError("receipt fields")
        if not ident(value["id"]) or not ident(value["account_id"]):
            raise ValueError("receipt id")
        if type(value["sequence"]) is not int or not 1 <= value["sequence"] <= 2147483647:
            raise ValueError("receipt sequence")
        if value["plan"] not in {"full", "basic"}:
            raise ValueError("receipt plan")
        if value["status"] not in {"active", "cancelled", "payment_failed"}:
            raise ValueError("receipt status")
        if value["id"] != receipt_id:
            raise ValueError("receipt id mismatch")
        return value
    except Exception as exc:
        # Provider protocol errors are never exposed as client-side malformed
        # request errors.  They mean the provider did not supply a canonical
        # record.
        if isinstance(exc, Problem):
            raise Problem(502, "provider_invalid_receipt") from exc
        raise Problem(502, "provider_invalid_receipt") from exc


def _reject_constant(_value):
    raise ValueError("non-finite JSON number")


def _strict_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _public_competitor(row) -> dict:  # noqa: ANN001
    return {
        "competitor_id": row["competitor_id"],
        "name": row["name"],
        "archived": bool(row["archived"]),
    }


def _subscription(db, owner: str):
    return db.execute(
        "SELECT account_id,sequence,plan,status,revocation_epoch "
        "FROM subscriptions WHERE account_id=?",
        (owner,),
    ).fetchone()


def _subscription_public(row) -> dict:  # noqa: ANN001
    if row is None:
        return {"sequence": 0, "plan": "basic", "status": "cancelled"}
    return {
        "sequence": int(row["sequence"]),
        "plan": row["plan"],
        "status": row["status"],
    }


def _writable(row) -> bool:  # noqa: ANN001
    return row is not None and row["plan"] == "full" and row["status"] == "active"


def _require_writable(db, owner: str) -> None:
    require(_writable(_subscription(db, owner)), "subscription_required", 403)


def authorize_creation(db, owner: str) -> None:
    """Directory creation is the one foundation operation requiring access."""
    _require_writable(db, owner)


def _competitor(db, owner: str, competitor_id: str):
    require(ident(competitor_id))
    row = db.execute(
        "SELECT * FROM competitors WHERE account_id=? AND competitor_id=?",
        (owner, competitor_id),
    ).fetchone()
    require(row is not None, "not_found", 404)
    return row


def _owned_url(db, owner: str, url_id: str):
    require(ident(url_id))
    row = db.execute(
        "SELECT u.*, c.archived, c.epoch AS competitor_epoch "
        "FROM urls AS u JOIN competitors AS c "
        "ON c.account_id=u.account_id AND c.competitor_id=u.competitor_id "
        "WHERE u.account_id=? AND u.url_id=?",
        (owner, url_id),
    ).fetchone()
    require(row is not None, "not_found", 404)
    return row


def _snapshot_public(row) -> dict:  # noqa: ANN001
    return {
        "snapshot_id": row["snapshot_id"],
        "url_id": row["url_id"],
        "observed_at_ms": int(row["observed_at_ms"]),
        "text": row["text"],
        "sha256": row["sha256"],
    }


def _snapshot_preflight(db, owner: str, snapshot_id: str, url_id: str, observed_at: int):
    """Check cheap replay/access/staleness conditions before contacting provider."""
    existing = db.execute(
        "SELECT * FROM snapshots WHERE account_id=? AND snapshot_id=?",
        (owner, snapshot_id),
    ).fetchone()
    if existing is not None:
        if existing["url_id"] == url_id and existing["observed_at_ms"] == observed_at:
            return {"duplicate": True, "snapshot": _snapshot_public(existing)}
        raise Problem(409, "snapshot_id_reused")

    # Ownership is deliberately resolved before the network request.
    url = _owned_url(db, owner, url_id)
    subscription = _subscription(db, owner)
    require(_writable(subscription), "subscription_required", 403)
    require(not bool(url["archived"]), "competitor_archived", 409)
    if url["observed_at_ms"] is not None:
        require(observed_at > url["observed_at_ms"], "stale_observation", 409)
    return {
        "duplicate": False,
        "competitor_epoch": int(url["competitor_epoch"]),
        "revocation_epoch": int(subscription["revocation_epoch"]),
    }


def _commit_snapshot(
    db,
    owner: str,
    snapshot_id: str,
    url_id: str,
    observed_at: int,
    text: str,
    digest: str,
    preflight: dict,
) -> tuple[dict, bool]:
    """Commit a fetched page, rechecking every state boundary."""
    with transaction(db):
        # This second lookup also resolves the allowed concurrent duplicate
        # case: only one request inserts the snapshot/event, and later requests
        # return the committed row as an exact duplicate.
        existing = db.execute(
            "SELECT * FROM snapshots WHERE account_id=? AND snapshot_id=?",
            (owner, snapshot_id),
        ).fetchone()
        if existing is not None:
            if existing["url_id"] == url_id and existing["observed_at_ms"] == observed_at:
                return _snapshot_public(existing), True
            raise Problem(409, "snapshot_id_reused")

        url = _owned_url(db, owner, url_id)
        subscription = _subscription(db, owner)
        # An archive/restore transition changes epoch even if the current row
        # is active again.  Likewise revocation_epoch records a full-active ->
        # non-writable transition across a later reactivation.
        if bool(url["archived"]) or int(url["competitor_epoch"]) != int(preflight["competitor_epoch"]):
            raise Problem(409, "snapshot_state_changed")
        if not _writable(subscription):
            current_epoch = int(subscription["revocation_epoch"]) if subscription is not None else 0
            if current_epoch != int(preflight["revocation_epoch"]):
                raise Problem(409, "snapshot_state_changed")
            raise Problem(403, "subscription_required")
        if int(subscription["revocation_epoch"]) != int(preflight["revocation_epoch"]):
            raise Problem(409, "snapshot_state_changed")
        if url["observed_at_ms"] is not None and observed_at <= url["observed_at_ms"]:
            raise Problem(409, "stale_observation")

        before_text = url["text"]
        before_digest = url["sha256"]
        db.execute(
            "INSERT INTO snapshots(account_id,snapshot_id,url_id,observed_at_ms,text,sha256) "
            "VALUES(?,?,?,?,?,?)",
            (owner, snapshot_id, url_id, observed_at, text, digest),
        )
        if before_text is not None and before_text != text:
            db.execute(
                "INSERT INTO events(account_id,snapshot_id,url_id,observed_at_ms,"
                "before_text,after_text,before_sha256,after_sha256) VALUES(?,?,?,?,?,?,?,?)",
                (
                    owner,
                    snapshot_id,
                    url_id,
                    observed_at,
                    before_text,
                    text,
                    before_digest,
                    digest,
                ),
            )
        db.execute(
            "UPDATE urls SET text=?,sha256=?,observed_at_ms=? "
            "WHERE account_id=? AND url_id=?",
            (text, digest, observed_at, owner, url_id),
        )
        return {
            "snapshot_id": snapshot_id,
            "url_id": url_id,
            "observed_at_ms": observed_at,
            "text": text,
            "sha256": digest,
        }, False


def _take_snapshot(db, owner: str, provider: str, body: dict) -> dict:
    fields(body, ["snapshot_id", "url_id", "observed_at_ms"])
    require(ident(body["snapshot_id"]))
    require(ident(body["url_id"]))
    require(timestamp(body["observed_at_ms"]))
    snapshot_id = body["snapshot_id"]
    url_id = body["url_id"]
    observed_at = body["observed_at_ms"]

    preflight = _snapshot_preflight(db, owner, snapshot_id, url_id, observed_at)
    if preflight["duplicate"]:
        return {"snapshot": preflight["snapshot"], "duplicate": True}

    # No transaction or other application write lock surrounds this request.
    text, digest = _fetch_page(provider, db.execute("SELECT url FROM urls WHERE account_id=? AND url_id=?", (owner, url_id)).fetchone()["url"])
    snapshot, duplicate = _commit_snapshot(
        db, owner, snapshot_id, url_id, observed_at, text, digest, preflight
    )
    return {"snapshot": snapshot, "duplicate": duplicate}


def _archive(db, owner: str, body: dict) -> dict:
    fields(body, ["competitor_id", "archived"])
    require(ident(body["competitor_id"]))
    require(type(body["archived"]) is bool)
    desired = 1 if body["archived"] else 0
    with transaction(db):
        row = _competitor(db, owner, body["competitor_id"])
        current = int(row["archived"])
        if current == desired:
            # Idempotent actions are not lifecycle transitions and therefore do
            # not invalidate an in-flight operation.
            return {"competitor": _public_competitor(row)}
        if desired == 0:
            # Only a real restore needs writable access.  An already-active
            # competitor was handled by the idempotent branch above.
            _require_writable(db, owner)
        db.execute(
            "UPDATE competitors SET archived=?,epoch=epoch+1 "
            "WHERE account_id=? AND competitor_id=?",
            (desired, owner, body["competitor_id"]),
        )
        return {
            "competitor": _public_competitor(
                _competitor(db, owner, body["competitor_id"])
            )
        }


def _history(db, owner: str, query: dict) -> list[dict]:
    fields(query, ["url_id"])
    _owned_url(db, owner, query["url_id"])
    rows = db.execute(
        "SELECT snapshot_id,url_id,observed_at_ms,before_text,after_text,before_sha256,after_sha256 "
        "FROM events WHERE account_id=? AND url_id=? "
        "ORDER BY observed_at_ms,snapshot_id",
        (owner, query["url_id"]),
    ).fetchall()
    return [dict(row) for row in rows]


def _history_csv(db, owner: str, query: dict):
    events = _history(db, owner, query)
    output = io.StringIO(newline="")
    writer = csv.writer(
        output,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writerow(
        [
            "snapshot_id",
            "observed_at_ms",
            "before_text",
            "after_text",
            "before_sha256",
            "after_sha256",
        ]
    )
    for event in events:
        writer.writerow(
            [
                event["snapshot_id"],
                event["observed_at_ms"],
                event["before_text"],
                event["after_text"],
                event["before_sha256"],
                event["after_sha256"],
            ]
        )
    return output.getvalue().encode("utf-8"), "text/csv", "changes.csv"


def _subscription_response(row, duplicate: bool) -> dict:
    public = _subscription_public(row)
    return {
        "subscription": public,
        "writable": public["plan"] == "full" and public["status"] == "active",
        "duplicate": duplicate,
    }


def _apply_receipt(db, owner: str, receipt: dict) -> dict:
    with transaction(db):
        current = _subscription(db, owner)
        existing = db.execute(
            "SELECT id,sequence,plan,status FROM receipts WHERE account_id=? AND id=?",
            (owner, receipt["id"]),
        ).fetchone()
        if existing is not None:
            same = (
                int(existing["sequence"]) == receipt["sequence"]
                and existing["plan"] == receipt["plan"]
                and existing["status"] == receipt["status"]
            )
            if not same:
                raise Problem(409, "receipt_reused")
            # A replay is deliberately read-only.  In particular, it does not
            # restore the old receipt's state after a later receipt was accepted.
            return _subscription_response(current, True)

        used_sequence = db.execute(
            "SELECT 1 FROM receipts WHERE account_id=? AND sequence=?",
            (owner, receipt["sequence"]),
        ).fetchone()
        current_sequence = int(current["sequence"]) if current is not None else 0
        if used_sequence is not None or receipt["sequence"] <= current_sequence:
            raise Problem(409, "receipt_sequence_conflict")

        old_writable = _writable(current)
        new_writable = receipt["plan"] == "full" and receipt["status"] == "active"
        old_epoch = int(current["revocation_epoch"]) if current is not None else 0
        new_epoch = old_epoch + (1 if old_writable and not new_writable else 0)
        db.execute(
            "INSERT INTO receipts(account_id,id,sequence,plan,status) VALUES(?,?,?,?,?)",
            (owner, receipt["id"], receipt["sequence"], receipt["plan"], receipt["status"]),
        )
        if current is None:
            db.execute(
                "INSERT INTO subscriptions(account_id,sequence,plan,status,revocation_epoch) "
                "VALUES(?,?,?,?,?)",
                (owner, receipt["sequence"], receipt["plan"], receipt["status"], new_epoch),
            )
        else:
            db.execute(
                "UPDATE subscriptions SET sequence=?,plan=?,status=?,revocation_epoch=? "
                "WHERE account_id=?",
                (
                    receipt["sequence"],
                    receipt["plan"],
                    receipt["status"],
                    new_epoch,
                    owner,
                ),
            )
        row = _subscription(db, owner)
        return _subscription_response(row, False)


def _subscription_dispatch(db, owner: str, provider: str, method: str, body: dict) -> dict:
    if method == "GET":
        fields(body, [])
        row = _subscription(db, owner)
        public = _subscription_public(row)
        return {
            "subscription": public,
            "writable": public["plan"] == "full" and public["status"] == "active",
        }
    fields(body, ["receipt_id"])
    require(ident(body["receipt_id"]))
    receipt = _fetch_receipt(provider, body["receipt_id"])
    # Do not write or reveal a canonical record belonging to another account.
    require(receipt["account_id"] == owner, "receipt_for_other_account", 403)
    return _apply_receipt(db, owner, receipt)


def dispatch(db, owner: str, provider: str, method: str, path: str, query: dict, body: dict):
    if method == "POST" and path == "/api/archive":
        return _archive(db, owner, body)
    if method == "POST" and path == "/api/snapshots":
        return _take_snapshot(db, owner, provider, body)
    if method == "GET" and path == "/api/history":
        return {"events": _history(db, owner, query)}
    if method == "GET" and path == "/api/history.csv":
        return _history_csv(db, owner, query)
    if path == "/api/subscription" and method in {"GET", "POST"}:
        return _subscription_dispatch(db, owner, provider, method, body if method == "POST" else query)
    raise Problem(404, "not_found")
