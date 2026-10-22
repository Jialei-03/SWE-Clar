"""Durable SQLite state for events, snapshots, and connector deliveries."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from reports import Failure, event, filters, identifier, report, export_csv, validate_export_path
from transport import deliver


class Store:
    def __init__(self, path, adapter):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.adapter = adapter

        # These are deliberately ordinary SQLite tables (rather than an
        # in-memory state mirror).  rowid is the durable insertion order for
        # events and deliveries; updating a row does not change that rowid.
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS events(
                source TEXT,
                event_id TEXT,
                record TEXT NOT NULL,
                PRIMARY KEY(source,event_id)
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot(
                id INTEGER PRIMARY KEY,
                meta TEXT NOT NULL,
                records TEXT NOT NULL
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries(
                request_id TEXT PRIMARY KEY,
                selection TEXT NOT NULL,
                record TEXT NOT NULL
            )
            """
        )
        self.db.execute(
            "INSERT OR IGNORE INTO snapshot(id,meta,records) VALUES(1,?,?)",
            (
                json.dumps(
                    {"version": 0, "record_count": 0, "watermark": None},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "[]",
            ),
        )

    @contextmanager
    def transaction(self):
        """Serialize a command and commit all of its SQLite changes together."""

        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            try:
                self.db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            self.db.execute("COMMIT")

    @staticmethod
    def _dump(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def records(self):
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT record FROM events ORDER BY rowid")
        ]

    def snapshot(self):
        row = self.db.execute(
            "SELECT meta,records FROM snapshot WHERE id=1"
        ).fetchone()
        if row is None:
            # Initialization always creates this row.  Treat its absence as an
            # environment/database failure rather than fabricating a snapshot.
            raise sqlite3.DatabaseError("snapshot row is missing")
        return json.loads(row[0]), json.loads(row[1])

    def deliveries(self):
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT record FROM deliveries ORDER BY rowid")
        ]

    def execute(self, command):
        if not isinstance(command, dict):
            raise Failure("invalid_request")

        op = command.get("op")
        operations = {
            "status",
            "records",
            "ingest",
            "refresh",
            "report",
            "export",
            "queue",
            "deliver",
            "deliveries",
        }
        if not isinstance(op, str) or op not in operations:
            raise Failure("unknown_operation")

        if op == "ingest":
            incoming = command.get("records")
            if not isinstance(incoming, list) or len(incoming) > 200:
                raise Failure("invalid_batch")
            # Complete validation happens before opening the write transaction,
            # so no invalid occurrence can partially affect durable state.
            normalized = [event(value) for value in incoming]
            with self.transaction():
                return self._ingest(normalized)

        if op == "refresh":
            watermark = command.get("watermark")
            if watermark is not None and not identifier(watermark):
                raise Failure("invalid_request")
            with self.transaction():
                return self._refresh(watermark)

        if op == "report":
            selection = filters(command)
            with self.transaction():
                meta, rows = self.snapshot()
                return report(rows, meta["version"], selection)

        if op == "export":
            # Validate both the filters and destination before reading the
            # snapshot or creating any filesystem output.
            selection = filters(command)
            validate_export_path(command.get("path"))
            with self.transaction():
                meta, rows = self.snapshot()
                value = report(rows, meta["version"], selection)
                return export_csv(command.get("path"), value)

        if op == "queue":
            target = command.get("target")
            if target not in ("table", "mail", "archive"):
                raise Failure("invalid_target")
            request_id = command.get("request_id")
            if not identifier(request_id):
                raise Failure("invalid_request")
            selection = filters(command)
            with self.transaction():
                return self._queue(request_id, target, selection)

        if op == "deliver":
            request_id = command.get("request_id")
            if not identifier(request_id):
                raise Failure("invalid_request")
            # Keep the network attempt inside the write transaction.  A second
            # process therefore waits for the first attempt's durable status
            # and cannot issue a second request after a successful delivery.
            with self.transaction():
                return self._deliver(request_id)

        if op == "status":
            with self.transaction():
                meta, _ = self.snapshot()
                record_count = self.db.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
                delivery_rows = self.db.execute(
                    "SELECT record FROM deliveries"
                ).fetchall()
                pending = 0
                delivered_count = 0
                for (encoded_delivery,) in delivery_rows:
                    status = json.loads(encoded_delivery)["status"]
                    if status == "pending":
                        pending += 1
                    elif status == "delivered":
                        delivered_count += 1
                return {
                    "record_count": record_count,
                    "snapshot": meta,
                    "pending_deliveries": pending,
                    "delivered_count": delivered_count,
                }

        if op == "records":
            with self.transaction():
                return {"records": self.records()}

        # The only remaining operation is deliveries.
        with self.transaction():
            return {"deliveries": self.deliveries()}

    def _ingest(self, rows):
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        for row in rows:
            key = (row["source"], row["event_id"])
            stored = self.db.execute(
                "SELECT record FROM events WHERE source=? AND event_id=?", key
            ).fetchone()
            encoded = self._dump(row)
            if stored is None:
                self.db.execute(
                    "INSERT INTO events(source,event_id,record) VALUES(?,?,?)",
                    (*key, encoded),
                )
                counts["inserted"] += 1
                continue

            previous = json.loads(stored[0])
            if row["revision"] > previous["revision"]:
                self.db.execute(
                    "UPDATE events SET record=? WHERE source=? AND event_id=?",
                    (encoded, *key),
                )
                counts["updated"] += 1
            elif row["revision"] == previous["revision"] and row == previous:
                counts["unchanged"] += 1
            else:
                # The surrounding transaction rolls back every earlier insert
                # and update in this batch.
                raise Failure("revision_conflict")

        record_count = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {**counts, "record_count": record_count}

    def _refresh(self, watermark):
        meta, previous = self.snapshot()
        current = self.records()
        if current != previous:
            meta = {
                "version": meta["version"] + 1,
                "record_count": len(current),
                "watermark": watermark,
            }
            self.db.execute(
                "UPDATE snapshot SET meta=?,records=? WHERE id=1",
                (self._dump(meta), self._dump(current)),
            )
        return meta

    def _queue(self, request_id, target, selection):
        row = self.db.execute(
            "SELECT selection,record FROM deliveries WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is not None:
            stored_selection = json.loads(row[0])
            stored_delivery = json.loads(row[1])
            if (
                stored_delivery["target"] != target
                or stored_selection != selection
            ):
                raise Failure("request_conflict")
            return {"delivery": stored_delivery}

        meta, rows = self.snapshot()
        value = report(rows, meta["version"], selection)
        delivery = {
            "request_id": request_id,
            "target": target,
            "envelope": {
                "request_id": request_id,
                "target": target,
                "report": value,
            },
            "status": "pending",
            "attempts": 0,
            "last_error": None,
        }
        self.db.execute(
            "INSERT INTO deliveries(request_id,selection,record) VALUES(?,?,?)",
            (request_id, self._dump(selection), self._dump(delivery)),
        )
        return {"delivery": delivery}

    def _deliver(self, request_id):
        row = self.db.execute(
            "SELECT record FROM deliveries WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise Failure("not_found")

        delivery = json.loads(row[0])
        if delivery["status"] == "delivered":
            return {"delivery": delivery}

        # transport.deliver performs one bounded HTTP attempt and returns only
        # a validated acknowledgement result.
        succeeded = deliver(self.adapter, delivery["envelope"])
        delivery["attempts"] += 1
        if succeeded:
            delivery["status"] = "delivered"
            delivery["last_error"] = None
        else:
            delivery["status"] = "pending"
            delivery["last_error"] = "delivery_failed"

        self.db.execute(
            "UPDATE deliveries SET record=? WHERE request_id=?",
            (self._dump(delivery), request_id),
        )
        return {"delivery": delivery}
