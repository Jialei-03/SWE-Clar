"""Local operator CLI; ``act`` outputs only the action's public envelope."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any


_DEFAULT_WHISPER_BIN = "/opt/sweclar/whisper-cli"
_DEFAULT_WHISPER_MODEL = "/opt/sweclar/ggml-tiny.en.bin"


def _json_error(code: str) -> dict[str, Any]:
    return {"error": {"code": code if isinstance(code, str) and code else "invalid"}}


def _dump(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="classroom.sqlite", metavar="PATH")
    parser.add_argument("--assets", default="/opt/sweclar/speech", metavar="DIR")
    parser.add_argument("command", choices=["init", "show", "act"])
    args = parser.parse_args()

    db: sqlite3.Connection | None = None
    try:
        db = sqlite3.connect(args.db, timeout=30)
        db.execute("PRAGMA busy_timeout = 30000")
        db.execute(
            "CREATE TABLE IF NOT EXISTS state("
            "id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)"
        )
        # A write transaction serializes operators and makes the state read,
        # action, and successful update one atomic SQLite transaction.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()

        if args.command == "init":
            if row is not None:
                db.rollback()
                print(_dump(_json_error("already_initialized")))
                return 0
            try:
                initial = json.load(sys.stdin)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                db.rollback()
                print(_dump(_json_error("invalid_state")))
                return 0
            if not isinstance(initial, dict):
                db.rollback()
                print(_dump(_json_error("invalid_state")))
                return 0
            body = _dump(initial)
            db.execute("INSERT INTO state(id,body) VALUES(1,?)", (body,))
            db.commit()
            print(_dump(initial))
            return 0

        if row is None:
            db.rollback()
            print(_dump(_json_error("not_initialized")))
            return 0

        try:
            state = json.loads(row[0])
        except (json.JSONDecodeError, TypeError, ValueError):
            db.rollback()
            print(_dump(_json_error("invalid_state")))
            return 0

        if args.command == "show":
            db.commit()
            print(_dump(state))
            return 0

        # act consumes exactly one JSON action.  Malformed input has no state
        # transition and, like a rejected action, exposes only an error.
        try:
            action = json.load(sys.stdin)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            db.rollback()
            print(_dump(_json_error("invalid_action")))
            return 0

        from solution import process_class_action
        from transcriber import LocalWhisper
        from translation_client import TranslationClient

        whisper_binary = os.environ.get("WHISPER_BIN", _DEFAULT_WHISPER_BIN)
        whisper_model = os.environ.get("WHISPER_MODEL", _DEFAULT_WHISPER_MODEL)
        transcriber = LocalWhisper(whisper_binary, whisper_model, args.assets)
        translation_url = os.environ.get("TRANSLATION_URL")
        translator = TranslationClient(translation_url) if translation_url else None
        next_state = process_class_action(state, action, transcriber, translator)
        if not isinstance(next_state, dict):
            db.rollback()
            print(_dump(_json_error("invalid_result")))
            return 0

        if "error" in next_state:
            # Do not write even if an adapter or a future action implementation
            # happened to put a transient field on its working copy.
            db.rollback()
            envelope = {"error": next_state.get("error")}
            if not isinstance(envelope["error"], dict) or not envelope["error"].get("code"):
                envelope = _json_error("invalid_result")
            print(_dump(envelope))
            return 0

        if "result" not in next_state:
            db.rollback()
            print(_dump(_json_error("invalid_result")))
            return 0

        # Response envelopes are not session business state.  Strip them before
        # persistence so show is a clean trusted inspection of the session.
        persisted = dict(next_state)
        persisted.pop("result", None)
        persisted.pop("error", None)
        body = _dump(persisted)
        db.execute("UPDATE state SET body=? WHERE id=1", (body,))
        db.commit()
        print(_dump({"result": next_state["result"]}))
        return 0
    except (OSError, sqlite3.Error, TypeError, ValueError, KeyError):
        if db is not None:
            try:
                db.rollback()
            except sqlite3.Error:
                pass
        print(_dump(_json_error("invalid")))
        return 0
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
