"""SQLite persistence for the independent local hiring application."""
import base64
import binascii
import hashlib
import json
import secrets
import sqlite3


def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + "$" + hashlib.pbkdf2_hmac(
        "sha256", value.encode("utf-8"), salt.encode("ascii"), 120000
    ).hex()


def public_user(row):
    return {key: row[key] for key in ("id", "name", "role", "bio")}


def _fixture_bytes(value):
    """Decode a fixture resume while keeping its exact bytes."""
    try:
        encoded = value.encode("ascii")
        content = base64.b64decode(encoded, validate=True)
    except (AttributeError, UnicodeEncodeError, binascii.Error, ValueError):
        raise ValueError("invalid fixture resume")
    return content


def _create_schema(db):
    # These are deliberately ordinary named SQLite tables: the database is a
    # first-class part of the local application and is also useful to inspect.
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            bio TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS relationships(
            actor_id TEXT NOT NULL REFERENCES users(id),
            target_id TEXT NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            PRIMARY KEY(actor_id,target_id,kind)
        );
        CREATE TABLE IF NOT EXISTS jobs(
            job_id TEXT PRIMARY KEY,
            employer_id TEXT NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            active INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookmarks(
            employee_id TEXT NOT NULL REFERENCES users(id),
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            PRIMARY KEY(employee_id,job_id)
        );
        CREATE TABLE IF NOT EXISTS resumes(
            resume_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id),
            filename TEXT NOT NULL,
            content BLOB NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS applications(
            application_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            employee_id TEXT NOT NULL REFERENCES users(id),
            resume_id TEXT REFERENCES resumes(resume_id),
            status TEXT NOT NULL,
            UNIQUE(job_id,employee_id)
        );
        CREATE TABLE IF NOT EXISTS interviews(
            interview_id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL UNIQUE REFERENCES applications(application_id),
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS views(
            viewer_id TEXT NOT NULL REFERENCES users(id),
            event_id TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            timestamp_ms INTEGER NOT NULL,
            PRIMARY KEY(viewer_id,event_id)
        );
        CREATE INDEX IF NOT EXISTS applications_employee_idx
            ON applications(employee_id,application_id);
        CREATE INDEX IF NOT EXISTS applications_resume_idx
            ON applications(resume_id);
        CREATE INDEX IF NOT EXISTS interviews_start_idx
            ON interviews(start_ms,interview_id);
        CREATE INDEX IF NOT EXISTS views_job_time_idx
            ON views(job_id,timestamp_ms);
        """
    )


def initialize(path, fixture):
    """Create schema and load fixtures exactly once for a new database."""
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        _create_schema(db)
        if db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():
            return

        data = json.loads(fixture.read_text(encoding="utf-8"))
        db.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('clock_ms',?)",
            (json.dumps(data["clock_ms"]),),
        )

        for record in data.get("users", []):
            db.execute(
                "INSERT INTO users(id,name,role,bio,password_hash) VALUES(?,?,?,?,?)",
                (
                    record["id"],
                    record["name"],
                    record["role"],
                    record["bio"],
                    password_hash(record["password"]),
                ),
            )

        for record in data.get("jobs", []):
            db.execute(
                """INSERT INTO jobs
                   (job_id,employer_id,title,description,category,location,active)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    record["job_id"],
                    record["employer_id"],
                    record["title"],
                    record["description"],
                    record["category"],
                    record["location"],
                    int(record["active"]),
                ),
            )

        for record in data.get("relationships", []):
            actor, target = record["actor_id"], record["target_id"]
            if record["kind"] == "connect":
                actor, target = sorted((actor, target))
            db.execute(
                "INSERT OR IGNORE INTO relationships(actor_id,target_id,kind) VALUES(?,?,?)",
                (actor, target, record["kind"]),
            )

        for record in data.get("resumes", []):
            content = _fixture_bytes(record["content_base64"])
            db.execute(
                """INSERT INTO resumes
                   (resume_id,owner_id,filename,content,size_bytes,sha256)
                   VALUES(?,?,?,?,?,?)""",
                (
                    record["resume_id"],
                    record["owner_id"],
                    record["filename"],
                    sqlite3.Binary(content),
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                ),
            )

        for record in data.get("applications", []):
            db.execute(
                """INSERT INTO applications
                   (application_id,job_id,employee_id,resume_id,status)
                   VALUES(?,?,?,?,?)""",
                tuple(record[key] for key in
                      ("application_id", "job_id", "employee_id", "resume_id", "status")),
            )

        for record in data.get("interviews", []):
            db.execute(
                """INSERT INTO interviews(interview_id,application_id,start_ms,end_ms)
                   VALUES(?,?,?,?)""",
                tuple(record[key] for key in
                      ("interview_id", "application_id", "start_ms", "end_ms")),
            )

        for record in data.get("views", []):
            db.execute(
                """INSERT INTO views(viewer_id,event_id,job_id,timestamp_ms)
                   VALUES(?,?,?,?)""",
                tuple(record[key] for key in
                      ("viewer_id", "event_id", "job_id", "timestamp_ms")),
            )

        db.execute("INSERT INTO meta(key,value) VALUES('initialized','true')")
