"""SQLite storage for the local scheduling service."""

import sqlite3


def connect(path):
    """Open the application database and ensure its persistent tables exist.

    The benchmark supplies a database which may already contain the seeded
    shifts table.  The other tables are deliberately created lazily so that a
    fresh database and a seeded database behave the same way.
    """
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS shifts(
            id TEXT PRIMARY KEY,
            starts_at TEXT NOT NULL,
            location TEXT NOT NULL,
            address TEXT NOT NULL,
            map_url TEXT NOT NULL,
            manager_email TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open'
        );

        CREATE TABLE IF NOT EXISTS signups(
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES employees(id),
            shift_id TEXT NOT NULL REFERENCES shifts(id),
            status TEXT NOT NULL DEFAULT 'New',
            checked_in INTEGER NOT NULL DEFAULT 0,
            UNIQUE(employee_id, shift_id)
        );

        CREATE TABLE IF NOT EXISTS deliveries(
            id TEXT PRIMARY KEY,
            signup_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT NOT NULL,
            body TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_employees_email ON employees(email);
        CREATE INDEX IF NOT EXISTS idx_signups_shift ON signups(shift_id);
        """
    )

    # Keep databases made by an earlier version usable.  These ALTERs are
    # intentionally limited to columns used by the public state contract.
    signup_columns = {
        row[1] for row in db.execute("PRAGMA table_info(signups)").fetchall()
    }
    if "status" not in signup_columns:
        db.execute(
            "ALTER TABLE signups ADD COLUMN status TEXT NOT NULL DEFAULT 'New'"
        )
    if "checked_in" not in signup_columns:
        db.execute(
            "ALTER TABLE signups ADD COLUMN checked_in INTEGER NOT NULL DEFAULT 0"
        )
    db.execute("CREATE INDEX IF NOT EXISTS idx_signups_status ON signups(status)")
    db.commit()
    return db
