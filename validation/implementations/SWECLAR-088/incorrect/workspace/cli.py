"""Local operator CLI; act outputs only the action's public envelope."""

import argparse
import copy
import json
import sqlite3
import sys


def _trusted_operator(state, admin_id):
    admins = state.get("admins") if isinstance(state, dict) else None
    if isinstance(admins, dict):
        return any(admin_id == candidate for candidate in admins.keys())
    if isinstance(admins, (list, tuple, set)):
        return any(admin_id == candidate for candidate in admins)
    return False


def _read_json_if_present():
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    return json.loads(raw)


def _cli_error(code="invalid"):
    return {"error": {"code": code or "invalid"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="licenses.sqlite")
    parser.add_argument(
        "--admin-id",
        "--admin",
        "--operator",
        dest="admin_id",
        help="trusted operator identity for the private show command",
    )
    parser.add_argument("command", choices=["init", "show", "act"])
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)"
        )
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()

        if args.command == "init":
            if row is not None:
                raise ValueError("already_initialized")
            initial = _read_json_if_present()
            if not isinstance(initial, dict):
                raise ValueError("invalid_state")
            db.execute(
                "INSERT INTO state VALUES(1,?)",
                (json.dumps(initial, allow_nan=False),),
            )
            output = initial
        else:
            if row is None:
                raise ValueError("not_initialized")
            current = json.loads(row[0])
            if not isinstance(current, dict):
                raise ValueError("invalid_state")

            if args.command == "show":
                request = _read_json_if_present()
                admin_id = args.admin_id
                if admin_id is None:
                    if isinstance(request, dict):
                        admin_id = request.get("admin_id", request.get("operator_id", request.get("admin")))
                    elif isinstance(request, str):
                        admin_id = request
                # The private operator view, including the deliveries outbox,
                # is available only to a trusted local operator.
                if not _trusted_operator(current, admin_id):
                    raise PermissionError("unauthorized")
                output = current
            else:  # act
                action = _read_json_if_present()
                if not isinstance(action, dict):
                    raise ValueError("invalid_action")
                from solution import process_license_action

                output = process_license_action(current, action)
                if not isinstance(output, dict):
                    raise ValueError("invalid_result")
                stored = copy.deepcopy(output)
                stored.pop("result", None)
                stored.pop("error", None)
                db.execute(
                    "UPDATE state SET body=? WHERE id=1",
                    (json.dumps(stored, allow_nan=False),),
                )

        db.commit()
        if args.command == "act":
            output = {key: output[key] for key in ("result", "error") if key in output}
        print(json.dumps(output, allow_nan=False))
    except PermissionError:
        db.rollback()
        print(json.dumps(_cli_error("unauthorized")))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        db.rollback()
        print(json.dumps(_cli_error("invalid")))
    finally:
        db.close()


if __name__ == "__main__":
    main()
