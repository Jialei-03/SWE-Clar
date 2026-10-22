"""SQLite persistence and quote calculation for the roof estimator."""

import copy
import json
import math
import os
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path


_CENT = Decimal("0.01")


class Store:
    def __init__(self, path, provider, pricing):
        self.path = str(path)
        self._uri = False
        self._memory_anchor = None
        if self.path == ":memory:":
            # Keep an anchor connection alive so each short-lived operation
            # can still use the same in-memory SQLite database.
            self._uri = True
            memory_name = "file:roof-store-" + secrets.token_hex(12) + "?mode=memory&cache=shared"
            self._connect_path = memory_name
            self._memory_anchor = sqlite3.connect(memory_name, uri=True, timeout=10)
        else:
            self._connect_path = self.path
        self.provider = provider
        # Take a private snapshot.  A request must not be able to change the
        # server's pricing by retaining and mutating the object supplied here.
        self.pricing = copy.deepcopy(pricing)
        parent = Path(self.path).parent
        if self.path not in {":memory:", ""}:
            parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions(
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS detections(
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id),
                    payload TEXT
                );
                CREATE TABLE IF NOT EXISTS quotes(
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id),
                    detection_id TEXT REFERENCES detections(id),
                    payload TEXT
                );
                CREATE TABLE IF NOT EXISTS leads(
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id),
                    quote_id TEXT REFERENCES quotes(id),
                    payload TEXT
                );
                CREATE INDEX IF NOT EXISTS detections_session
                    ON detections(session_id);
                CREATE INDEX IF NOT EXISTS quotes_session_detection
                    ON quotes(session_id, detection_id);
                CREATE INDEX IF NOT EXISTS quotes_session_id
                    ON quotes(session_id, id);
                CREATE INDEX IF NOT EXISTS leads_session_id
                    ON leads(session_id, id);
                """
            )
        if self.path not in {":memory:", ""}:
            # Detection, quote, and lead payloads are private server data.
            # Do not leave a newly created SQLite file world-readable under a
            # permissive process umask.
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                # A later write will report the underlying filesystem error;
                # schema setup itself should not hide it with a permission
                # normalization failure.
                pass

    def connect(self):
        db = sqlite3.connect(self._connect_path, timeout=10, uri=self._uri)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _finite_number(value, positive=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid_detection")
        try:
            valid = math.isfinite(value)
        except (OverflowError, TypeError):
            valid = False
        if not valid or (positive and value <= 0):
            raise ValueError("invalid_detection")
        return float(value)

    @classmethod
    def _canonical_location(cls, value):
        if not isinstance(value, dict):
            raise ValueError("invalid_detection")
        latitude = cls._finite_number(value.get("latitude"))
        longitude = cls._finite_number(value.get("longitude"))
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("invalid_detection")
        return {"latitude": latitude, "longitude": longitude}

    @classmethod
    def _canonical_detection(cls, result, address, detection_id):
        if not isinstance(result, dict):
            raise ValueError("invalid_detection")
        try:
            area = cls._finite_number(result["area_m2"], positive=True)
            center = cls._canonical_location(result["center"])
            bounds = result["bounds"]
            if not isinstance(bounds, dict):
                raise ValueError("invalid_detection")
            south_west = cls._canonical_location(bounds["sw"])
            north_east = cls._canonical_location(bounds["ne"])
        except (KeyError, TypeError):
            raise ValueError("invalid_detection") from None
        if not cls._nonempty(address):
            raise ValueError("invalid_detection")
        if (
            not south_west["latitude"] < north_east["latitude"]
            or not south_west["longitude"] < north_east["longitude"]
            or not south_west["latitude"] <= center["latitude"] <= north_east["latitude"]
            or not south_west["longitude"] <= center["longitude"] <= north_east["longitude"]
        ):
            raise ValueError("invalid_detection")
        return {
            "detection_id": detection_id,
            "address": address,
            "area_m2": area,
            "center": center,
            "bounds": {"sw": south_west, "ne": north_east},
        }

    @staticmethod
    def _decimal(value, error="invalid_rate"):
        # Pricing is configuration, not caller input.  Still reject strings
        # and booleans so a malformed config cannot quietly become a price.
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(error)
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(error) from None
        if not result.is_finite() or result < 0:
            raise ValueError(error)
        return result

    @classmethod
    def _amount(cls, area, rate):
        try:
            area_decimal = Decimal(str(area))
            rate_decimal = cls._decimal(rate)
            # Give quantize enough precision for the integer part as well as
            # the cents.  This keeps the arithmetic decimal and half-up even
            # for a large, but finite, provider area.
            integer_digits = max(0, area_decimal.adjusted() + rate_decimal.adjusted() + 1)
            precision = max(
                28,
                integer_digits
                + len(area_decimal.as_tuple().digits)
                + len(rate_decimal.as_tuple().digits)
                + 4,
            )
            with localcontext() as context:
                context.prec = precision
                return (area_decimal * rate_decimal).quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            raise ValueError("invalid_rate") from None

    @staticmethod
    def _money(value):
        # _amount and the total calculation already produce a two-place
        # Decimal.  Formatting it directly avoids a low global Decimal
        # context truncating a valid large amount.
        return format(value, ".2f")

    @staticmethod
    def _new_id():
        return secrets.token_hex(16)

    def session(self, ident):
        """Return a valid browser session id, creating one when necessary."""
        with self.connect() as db:
            if self._nonempty(ident):
                row = db.execute("SELECT id FROM sessions WHERE id=?", (ident,)).fetchone()
                if row:
                    return ident, False
            # A random value is generated server-side; a caller cannot choose
            # an id which collides with or aliases another browser session.
            while True:
                generated = secrets.token_hex(24)
                try:
                    db.execute("INSERT INTO sessions(id) VALUES (?)", (generated,))
                    return generated, True
                except sqlite3.IntegrityError:
                    continue

    def detect(self, sid, address):
        """Resolve and persist one successful detection for *sid*."""
        if not self._nonempty(sid) or not isinstance(address, str) or not address.strip():
            raise ValueError("invalid_address")
        submitted_address = address.strip()
        # Nothing is written until the complete provider response has been
        # validated.  In particular, a provider timeout cannot replace the
        # last successful detection for this session.
        result = self.provider.find(submitted_address)
        detection_id = self._new_id()
        detection = self._canonical_detection(result, submitted_address, detection_id)
        payload = json.dumps(detection, allow_nan=False, separators=(",", ":"))
        with self.connect() as db:
            try:
                db.execute(
                    "INSERT INTO detections(id,session_id,payload) VALUES (?,?,?)",
                    (detection_id, sid, payload),
                )
            except sqlite3.IntegrityError:
                # This normally means a caller supplied a session which was
                # not issued by session().  Do not leave a half-record.
                raise PermissionError("session_denied") from None
        return detection

    def current(self, sid):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM detections WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if not row:
                return {"detection": None, "quote": None}
            quote = db.execute(
                "SELECT payload FROM quotes "
                "WHERE session_id=? AND detection_id=? ORDER BY rowid DESC LIMIT 1",
                (sid, row["id"]),
            ).fetchone()
            return {
                "detection": json.loads(row["payload"]),
                "quote": json.loads(quote["payload"]) if quote else None,
            }

    def quote(self, sid, action):
        """Calculate and atomically persist a quote for a session detection."""
        if not self._nonempty(sid) or not isinstance(action, dict):
            raise ValueError("invalid_quote")

        detection_id = action.get("detection_id")
        roof_type = action.get("roof_type")
        material = action.get("material")
        extras = action.get("extras")
        if (
            not self._nonempty(detection_id)
            or not self._nonempty(roof_type)
            or not self._nonempty(material)
            or not isinstance(extras, list)
        ):
            raise ValueError("invalid_quote")
        if any(not isinstance(extra, str) or not self._nonempty(extra) for extra in extras):
            raise ValueError("invalid_quote")
        if len(set(extras)) != len(extras):
            raise ValueError("duplicate_extra")

        pricing = self.pricing
        if not isinstance(pricing, dict):
            raise ValueError("invalid_rate")
        roof_prices = pricing.get("roof_type")
        material_prices = pricing.get("material")
        extra_prices = pricing.get("extras")
        if (
            not isinstance(roof_prices, dict)
            or not isinstance(material_prices, dict)
            or not isinstance(extra_prices, dict)
            or roof_type not in roof_prices
            or material not in material_prices
            or any(extra not in extra_prices for extra in extras)
        ):
            raise ValueError("unknown_choice")

        # Validate and calculate only selected choices.  An unused malformed
        # optional catalogue entry must not make an otherwise valid quote
        # impossible, while every rate that contributes to this quote is
        # checked strictly.
        selected_rates = [roof_prices[roof_type], material_prices[material]]
        selected_rates.extend(extra_prices[extra] for extra in extras)
        rates = [self._decimal(rate) for rate in selected_rates]

        # The lookup is part of the same write transaction as the insert.  A
        # foreign detection is never usable, even if its id is known.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id,payload FROM detections WHERE id=? AND session_id=?",
                (detection_id, sid),
            ).fetchone()
            if not row:
                raise PermissionError("detection_denied")
            try:
                detection = json.loads(row["payload"])
            except (TypeError, ValueError):
                raise ValueError("invalid_detection") from None
            # Revalidate persisted data as a defence against a damaged or
            # externally edited database.  The caller's area is never read.
            if not isinstance(detection, dict):
                raise ValueError("invalid_detection")
            detection = self._canonical_detection(
                detection, detection.get("address"), row["id"]
            )

            area = detection["area_m2"]
            amounts = [self._amount(area, rate) for rate in rates]
            try:
                total_integer_digits = max(
                    [0] + [max(0, amount.adjusted() + 1) for amount in amounts]
                )
                with localcontext() as context:
                    context.prec = max(28, total_integer_digits + len(amounts) + 4)
                    total_decimal = sum(amounts, Decimal("0.00")).quantize(
                        _CENT, rounding=ROUND_HALF_UP
                    )
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                raise ValueError("invalid_rate") from None
            items = [
                {"kind": "roof_type", "name": roof_type, "amount": self._money(amounts[0])},
                {"kind": "material", "name": material, "amount": self._money(amounts[1])},
            ]
            items.extend(
                {
                    "kind": "extra",
                    "name": extra,
                    "amount": self._money(amount),
                }
                for extra, amount in zip(extras, amounts[2:])
            )
            quote_id = self._new_id()
            quote = {
                "quote_id": quote_id,
                "detection_id": row["id"],
                "address": detection["address"],
                "area_m2": area,
                "roof_type": roof_type,
                "material": material,
                # Copy the list so the result is independent of the caller's
                # mutable action object.
                "extras": list(extras),
                "items": items,
                "total": self._money(total_decimal),
            }
            payload = json.dumps(quote, allow_nan=False, separators=(",", ":"))
            db.execute(
                "INSERT INTO quotes(id,session_id,detection_id,payload) VALUES (?,?,?,?)",
                (quote_id, sid, row["id"], payload),
            )
            return quote

    def lead(self, sid, action):
        """Persist a session-owned enquiry, with lead-id idempotency."""
        if not self._nonempty(sid) or not isinstance(action, dict):
            raise ValueError("invalid_contact")
        lead_id = action.get("lead_id")
        if not self._nonempty(lead_id):
            raise ValueError("missing_contact")
        lead_id = lead_id.strip()

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            if old:
                if old["session_id"] != sid:
                    raise PermissionError("lead_denied")
                try:
                    return json.loads(old["payload"])
                except (TypeError, ValueError):
                    raise ValueError("invalid_contact") from None

            required = ("quote_id", "name", "email", "phone", "address")
            if any(not self._nonempty(action.get(key)) for key in required):
                raise ValueError("missing_contact")
            quote_id = action["quote_id"]
            quote_row = db.execute(
                "SELECT id,payload FROM quotes WHERE id=? AND session_id=?",
                (quote_id, sid),
            ).fetchone()
            if not quote_row:
                raise PermissionError("quote_denied")
            try:
                quote = json.loads(quote_row["payload"])
            except (TypeError, ValueError):
                raise ValueError("invalid_quote") from None
            if not isinstance(quote, dict) or not self._nonempty(quote.get("address")):
                raise ValueError("invalid_quote")
            if action["address"].strip() != quote["address"]:
                raise ValueError("address_mismatch")

            result = {
                "lead_id": lead_id.strip(),
                "quote_id": quote_row["id"],
                "name": action["name"].strip(),
                "email": action["email"].strip(),
                "phone": action["phone"].strip(),
                "address": action["address"].strip(),
                "quote": quote,
            }
            payload = json.dumps(result, allow_nan=False, separators=(",", ":"))
            db.execute(
                "INSERT INTO leads(id,session_id,quote_id,payload) VALUES (?,?,?,?)",
                (lead_id, sid, quote_row["id"], payload),
            )
            return result
