"""Business workflows for the local synthetic hiring marketplace."""
import base64
import binascii
import csv
import datetime as _datetime
import hashlib
import io
import json
import re
import sqlite3

from common import Problem, fields, ident, optional_fields, require, text, timestamp
from storage import public_user


_JOB_COLUMNS = (
    "job_id",
    "employer_id",
    "title",
    "description",
    "category",
    "location",
    "active",
)
_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}\.txt\Z", re.IGNORECASE)
_QUERY_INT_RE = re.compile(r"-?[0-9]+\Z")
_MAX_INTERVIEW_MS = 8 * 60 * 60 * 1000


def _job_public(row):
    return {
        "job_id": row["job_id"],
        "employer_id": row["employer_id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "location": row["location"],
        "active": bool(row["active"]),
    }


def _job_row(db, job_id):
    return db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()


def _clock_ms(db):
    row = db.execute("SELECT value FROM meta WHERE key='clock_ms'").fetchone()
    require(row is not None, "storage_unavailable", 503)
    try:
        value = json.loads(row["value"])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise Problem(503, "storage_unavailable")
    require(timestamp(value), "storage_unavailable", 503)
    return value


def relationships(db, user):
    rows = db.execute(
        """SELECT actor_id,target_id,kind FROM relationships
           WHERE actor_id=? OR target_id=?
           ORDER BY kind,actor_id,target_id""",
        (user["id"], user["id"]),
    )
    return [dict(row) for row in rows]


def _application_row(db, application_id):
    return db.execute(
        """SELECT a.application_id,a.job_id,a.employee_id,a.resume_id,a.status,
                  j.employer_id,j.title AS job_title
           FROM applications AS a
           JOIN jobs AS j ON j.job_id=a.job_id
           WHERE a.application_id=?""",
        (application_id,),
    ).fetchone()


def _application_public(row):
    return {
        "application_id": row["application_id"],
        "job_id": row["job_id"],
        "employee_id": row["employee_id"],
        "employer_id": row["employer_id"],
        "job_title": row["job_title"],
        "resume_id": row["resume_id"],
        "status": row["status"],
    }


def _interview_public(row, participants=None):
    return {
        **({"participants": list(participants)} if participants is not None else {}),
        "interview_id": row["interview_id"],
        "application_id": row["application_id"],
        "start_ms": row["start_ms"],
        "end_ms": row["end_ms"],
    }


def _query_timestamp(value):
    require(isinstance(value, str) and _QUERY_INT_RE.fullmatch(value) is not None)
    try:
        result = int(value, 10)
    except (TypeError, ValueError, OverflowError):
        raise Problem(400, "invalid")
    require(timestamp(result))
    return result


def _period(query):
    has_start = "start_ms" in query
    has_end = "end_ms" in query
    require(has_start == has_end)
    if not has_start:
        return None
    start = _query_timestamp(query["start_ms"])
    end = _query_timestamp(query["end_ms"])
    require(start <= end)
    return start, end


def _job_fields(body, active=False):
    names = ["job_id", "title", "description", "category", "location"]
    if active:
        names.append("active")
    fields(body, names)
    require(ident(body["job_id"]))
    result = {
        "job_id": body["job_id"],
        "title": text(body["title"], 160),
        "description": text(body["description"], 10000),
        "category": text(body["category"], 80),
        "location": text(body["location"], 80),
    }
    if active:
        require(type(body["active"]) is bool)
        result["active"] = body["active"]
    return result


def _bookmark_jobs(db, user_id):
    rows = db.execute(
        """SELECT j.* FROM bookmarks AS b
           JOIN jobs AS j ON j.job_id=b.job_id
           WHERE b.employee_id=? ORDER BY j.job_id""",
        (user_id,),
    )
    return [_job_public(row) for row in rows]


def _resume_public(row):
    return {
        "resume_id": row["resume_id"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
    }


def _decode_resume(body):
    require(isinstance(body["filename"], str))
    filename = body["filename"]
    require(
        filename.isascii()
        and 1 <= len(filename) <= 80
        and _FILENAME_RE.fullmatch(filename) is not None
    )
    encoded = body["content_base64"]
    require(isinstance(encoded, str))
    try:
        raw = encoded.encode("ascii")
        content = base64.b64decode(raw, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise Problem(400, "invalid")
    # Re-encoding rejects noncanonical padding and alternate spellings.
    require(base64.b64encode(content).decode("ascii") == encoded)
    require(1 <= len(content) <= 262144)
    require(b"\x00" not in content)
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise Problem(400, "invalid")
    return filename, content


def _analytics_data(db, job_id, period):
    params = [job_id]
    sql = "SELECT viewer_id,timestamp_ms FROM views WHERE job_id=?"
    if period is not None:
        sql += " AND timestamp_ms>=? AND timestamp_ms<=?"
        params.extend(period)
    rows = list(db.execute(sql, params))
    by_day = {}
    all_viewers = set()
    for row in rows:
        timestamp_value = row["timestamp_ms"]
        day = (
            _datetime.datetime(1970, 1, 1, tzinfo=_datetime.timezone.utc)
            + _datetime.timedelta(milliseconds=timestamp_value)
        ).date().isoformat()
        record = by_day.setdefault(day, {"views": 0, "viewers": set()})
        record["views"] += 1
        record["viewers"].add(row["viewer_id"])
        all_viewers.add(row["viewer_id"])
    daily = [
        {
            "day": day,
            "views": by_day[day]["views"],
            "unique_viewers": len(by_day[day]["viewers"]),
        }
        for day in sorted(by_day)
    ]
    return {
        "job_id": job_id,
        "views": len(rows),
        "unique_viewers": len(all_viewers),
        "by_day": daily,
    }


def _analytics_csv(data):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("day", "views", "unique_viewers"))
    for row in data["by_day"]:
        writer.writerow((row["day"], row["views"], row["unique_viewers"]))
    return output.getvalue().encode("utf-8")


def _dispatch_profiles_and_relationships(db, user, method, path, query, body):
    if method == "GET" and path == "/api/profiles":
        fields(query, [])
        return {
            "profiles": [
                public_user(row)
                for row in db.execute("SELECT * FROM users ORDER BY id")
            ]
        }

    if method == "PUT" and path == "/api/profile":
        fields(body, ["name", "bio"])
        name = text(body["name"], 120)
        # Biography whitespace and markup are data, not formatting.
        bio = text(body["bio"], 2000, nonempty=False, trim=False)
        db.execute("UPDATE users SET name=?,bio=? WHERE id=?", (name, bio, user["id"]))
        return {
            "user": public_user(
                db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            )
        }

    if method == "GET" and path == "/api/relationships":
        fields(query, [])
        return {"relationships": relationships(db, user)}

    if method == "POST" and path == "/api/relationships":
        fields(body, ["target_id", "kind", "enabled"])
        require(ident(body["target_id"]))
        require(body["kind"] in ("follow", "connect"))
        require(type(body["enabled"]) is bool)
        target = db.execute("SELECT * FROM users WHERE id=?", (body["target_id"],)).fetchone()
        require(target is not None, "not_found", 404)
        require(target["id"] != user["id"])
        valid = (
            body["kind"] == "follow" and target["role"] == "employer"
        ) or (
            body["kind"] == "connect"
            and user["role"] == "employee"
            and target["role"] == "employee"
        )
        require(valid, "forbidden", 403)
        if body["kind"] == "connect":
            actor_id, target_id = sorted((user["id"], target["id"]))
        else:
            actor_id, target_id = user["id"], target["id"]
        if body["enabled"]:
            db.execute(
                "INSERT OR IGNORE INTO relationships(actor_id,target_id,kind) VALUES(?,?,?)",
                (actor_id, target_id, body["kind"]),
            )
        else:
            db.execute(
                "DELETE FROM relationships WHERE actor_id=? AND target_id=? AND kind=?",
                (actor_id, target_id, body["kind"]),
            )
        return {"relationships": relationships(db, user)}

    return None


def _dispatch_jobs(db, user, method, path, query, body):
    if method == "GET" and path == "/api/jobs":
        optional_fields(query, ("q", "category", "location"))
        q = query.get("q", "").strip().casefold()
        category = query.get("category", "").strip().casefold()
        location = query.get("location", "").strip().casefold()
        if user["role"] == "employer":
            rows = db.execute(
                "SELECT * FROM jobs WHERE employer_id=? ORDER BY job_id", (user["id"],)
            )
        else:
            rows = db.execute("SELECT * FROM jobs WHERE active=1 ORDER BY job_id")
        result = []
        for row in rows:
            if q and not (
                q in row["title"].casefold()
                or q in row["description"].casefold()
            ):
                continue
            if category and row["category"].strip().casefold() != category:
                continue
            if location and row["location"].strip().casefold() != location:
                continue
            result.append(_job_public(row))
        return {"jobs": result}

    if method == "POST" and path == "/api/jobs":
        value = _job_fields(body)
        require(user["role"] == "employer", "forbidden", 403)
        require(_job_row(db, value["job_id"]) is None, "conflict", 409)
        db.execute(
            """INSERT INTO jobs
               (job_id,employer_id,title,description,category,location,active)
               VALUES(?,?,?,?,?,?,1)""",
            (
                value["job_id"],
                user["id"],
                value["title"],
                value["description"],
                value["category"],
                value["location"],
            ),
        )
        return {"job": _job_public(_job_row(db, value["job_id"]))}

    if method == "PUT" and path == "/api/jobs":
        value = _job_fields(body, active=True)
        row = _job_row(db, value["job_id"])
        require(row is not None, "not_found", 404)
        require(user["role"] == "employer", "forbidden", 403)
        require(row["employer_id"] == user["id"], "forbidden", 403)
        db.execute(
            """UPDATE jobs SET title=?,description=?,category=?,location=?,active=?
               WHERE job_id=?""",
            (
                value["title"],
                value["description"],
                value["category"],
                value["location"],
                int(value["active"]),
                value["job_id"],
            ),
        )
        return {"job": _job_public(_job_row(db, value["job_id"]))}

    if method == "GET" and path == "/api/job":
        fields(query, ["job_id"])
        require(ident(query["job_id"]))
        row = _job_row(db, query["job_id"])
        require(row is not None, "not_found", 404)
        allowed = row["employer_id"] == user["id"] or (
            user["role"] == "employee" and bool(row["active"])
        )
        require(allowed, "forbidden", 403)
        return {"job": _job_public(row)}

    if method == "GET" and path == "/api/bookmarks":
        fields(query, [])
        require(user["role"] == "employee", "forbidden", 403)
        return {"jobs": _bookmark_jobs(db, user["id"])}

    if method == "POST" and path == "/api/bookmarks":
        fields(body, ["job_id", "enabled"])
        require(user["role"] == "employee", "forbidden", 403)
        require(ident(body["job_id"]))
        require(type(body["enabled"]) is bool)
        row = _job_row(db, body["job_id"])
        require(row is not None, "not_found", 404)
        if body["enabled"]:
            require(bool(row["active"]), "conflict", 409)
            db.execute(
                "INSERT OR IGNORE INTO bookmarks(employee_id,job_id) VALUES(?,?)",
                (user["id"], body["job_id"]),
            )
        else:
            db.execute(
                "DELETE FROM bookmarks WHERE employee_id=? AND job_id=?",
                (user["id"], body["job_id"]),
            )
        return {"jobs": _bookmark_jobs(db, user["id"])}

    return None


def _dispatch_resumes(db, user, method, path, query, body):
    if method == "POST" and path == "/api/resumes":
        fields(body, ["resume_id", "filename", "content_base64"])
        require(user["role"] == "employee", "forbidden", 403)
        require(ident(body["resume_id"]))
        filename, content = _decode_resume(body)
        existing = db.execute(
            "SELECT * FROM resumes WHERE resume_id=?", (body["resume_id"],)
        ).fetchone()
        if existing is not None:
            same = (
                existing["owner_id"] == user["id"]
                and existing["filename"] == filename
                and bytes(existing["content"]) == content
            )
            require(same, "conflict", 409)
            return {"resume": _resume_public(existing), "duplicate": True}
        digest = hashlib.sha256(content).hexdigest()
        db.execute(
            """INSERT INTO resumes
               (resume_id,owner_id,filename,content,size_bytes,sha256)
               VALUES(?,?,?,?,?,?)""",
            (
                body["resume_id"],
                user["id"],
                filename,
                sqlite3.Binary(content),
                len(content),
                digest,
            ),
        )
        row = db.execute(
            "SELECT * FROM resumes WHERE resume_id=?", (body["resume_id"],)
        ).fetchone()
        return {"resume": _resume_public(row), "duplicate": False}

    if method == "GET" and path == "/api/resume":
        fields(query, ["resume_id"])
        require(ident(query["resume_id"]))
        row = db.execute(
            "SELECT * FROM resumes WHERE resume_id=?", (query["resume_id"],)
        ).fetchone()
        # A nonexistent identifier is intentionally indistinguishable from a
        # resume owned by another account at this endpoint.
        require(row is not None, "forbidden", 403)
        allowed = row["owner_id"] == user["id"]
        if not allowed and user["role"] == "employer":
            allowed = (
                db.execute(
                    """SELECT 1 FROM applications AS a
                       JOIN jobs AS j ON j.job_id=a.job_id
                       WHERE a.resume_id=? AND j.employer_id=? LIMIT 1""",
                    (query["resume_id"], user["id"]),
                ).fetchone()
                is not None
            )
        require(allowed, "forbidden", 403)
        return (bytes(row["content"]), "text/plain", row["filename"])

    return None


def _dispatch_applications(db, user, method, path, query, body):
    if method == "GET" and path == "/api/applications":
        fields(query, [])
        if user["role"] == "employee":
            rows = db.execute(
                """SELECT a.application_id,a.job_id,a.employee_id,a.resume_id,a.status,
                          j.employer_id,j.title AS job_title
                   FROM applications AS a JOIN jobs AS j ON j.job_id=a.job_id
                   WHERE a.employee_id=? ORDER BY a.application_id""",
                (user["id"],),
            )
        else:
            rows = db.execute(
                """SELECT a.application_id,a.job_id,a.employee_id,a.resume_id,a.status,
                          j.employer_id,j.title AS job_title
                   FROM applications AS a JOIN jobs AS j ON j.job_id=a.job_id
                   WHERE j.employer_id=? ORDER BY a.application_id""",
                (user["id"],),
            )
        return {"applications": [_application_public(row) for row in rows]}

    if method == "POST" and path == "/api/applications":
        fields(body, ["application_id", "job_id", "resume_id"])
        require(user["role"] == "employee", "forbidden", 403)
        require(ident(body["application_id"]) and ident(body["job_id"]))
        resume_id = body["resume_id"]
        require(resume_id is None or ident(resume_id))

        existing_id = db.execute(
            "SELECT * FROM applications WHERE application_id=?",
            (body["application_id"],),
        ).fetchone()
        if existing_id is not None:
            same = (
                existing_id["job_id"] == body["job_id"]
                and existing_id["employee_id"] == user["id"]
                and existing_id["resume_id"] == resume_id
            )
            require(same, "conflict", 409)
            return {
                "application": _application_public(
                    _application_row(db, body["application_id"])
                ),
                "duplicate": True,
            }

        pair = db.execute(
            "SELECT application_id FROM applications WHERE job_id=? AND employee_id=?",
            (body["job_id"], user["id"]),
        ).fetchone()
        require(pair is None, "conflict", 409)

        if resume_id is not None:
            resume = db.execute(
                "SELECT owner_id FROM resumes WHERE resume_id=?", (resume_id,)
            ).fetchone()
            require(resume is not None and resume["owner_id"] == user["id"], "forbidden", 403)

        job = _job_row(db, body["job_id"])
        require(job is not None, "not_found", 404)
        require(bool(job["active"]), "conflict", 409)
        db.execute(
            """INSERT INTO applications
               (application_id,job_id,employee_id,resume_id,status)
               VALUES(?,?,?,?,?)""",
            (body["application_id"], body["job_id"], user["id"], resume_id, "applied"),
        )
        return {
            "application": _application_public(
                _application_row(db, body["application_id"])
            ),
            "duplicate": False,
        }

    return None


def _dispatch_rejection(db, user, method, path, query, body):
    if method == "POST" and path == "/api/reject":
        fields(body, ["application_id"])
        require(ident(body["application_id"]))
        require(user["role"] == "employer", "forbidden", 403)
        row = _application_row(db, body["application_id"])
        # This endpoint intentionally does not reveal whether another
        # employer's or nonexistent application exists.
        require(row is not None and row["employer_id"] == user["id"], "forbidden", 403)
        db.execute("DELETE FROM interviews WHERE application_id=?", (body["application_id"],))
        db.execute(
            "UPDATE applications SET status='rejected' WHERE application_id=?",
            (body["application_id"],),
        )
        return {"application": _application_public(_application_row(db, body["application_id"]))}
    return None


def _dispatch_interviews(db, user, method, path, query, body):
    if method == "POST" and path == "/api/interviews":
        fields(body, ["interview_id", "application_id", "start_ms", "end_ms"])
        require(ident(body["interview_id"]) and ident(body["application_id"]))
        require(timestamp(body["start_ms"]) and timestamp(body["end_ms"]))
        require(body["end_ms"] > body["start_ms"])
        require(body["start_ms"] >= _clock_ms(db))
        require(body["end_ms"] - body["start_ms"] <= _MAX_INTERVIEW_MS)
        require(user["role"] == "employer", "forbidden", 403)

        app = _application_row(db, body["application_id"])
        require(app is not None and app["employer_id"] == user["id"], "forbidden", 403)

        existing_id = db.execute(
            "SELECT * FROM interviews WHERE interview_id=?", (body["interview_id"],)
        ).fetchone()
        if existing_id is not None:
            same = (
                existing_id["application_id"] == body["application_id"]
                and existing_id["start_ms"] == body["start_ms"]
                and existing_id["end_ms"] == body["end_ms"]
            )
            require(same, "conflict", 409)
            return {
                "interview": _interview_public(existing_id, [app["employer_id"], app["employee_id"]]),
                "duplicate": True,
            }

        scheduled = db.execute(
            "SELECT * FROM interviews WHERE application_id=?",
            (body["application_id"],),
        ).fetchone()
        require(scheduled is None, "conflict", 409)
        require(app["status"] != "rejected", "conflict", 409)

        overlap = db.execute(
            """SELECT 1
               FROM interviews AS i
               JOIN applications AS a ON a.application_id=i.application_id
               JOIN jobs AS j ON j.job_id=a.job_id
               WHERE (j.employer_id=? OR a.employee_id=?)
                 AND i.start_ms < ? AND i.end_ms > ?
               LIMIT 1""",
            (
                user["id"],
                app["employee_id"],
                body["end_ms"],
                body["start_ms"],
            ),
        ).fetchone()
        require(overlap is None, "conflict", 409)
        db.execute(
            "INSERT INTO interviews(interview_id,application_id,start_ms,end_ms) VALUES(?,?,?,?)",
            (
                body["interview_id"],
                body["application_id"],
                body["start_ms"],
                body["end_ms"],
            ),
        )
        db.execute(
            "UPDATE applications SET status='scheduled' WHERE application_id=?",
            (body["application_id"],),
        )
        row = db.execute(
            "SELECT * FROM interviews WHERE interview_id=?", (body["interview_id"],)
        ).fetchone()
        return {"interview": _interview_public(row, [app["employer_id"], app["employee_id"]]), "duplicate": False}

    if method == "GET" and path == "/api/calendar":
        fields(query, [])
        if user["role"] == "employee":
            where, value = "a.employee_id=?", user["id"]
        else:
            where, value = "j.employer_id=?", user["id"]
        rows = db.execute(
            f"""SELECT i.interview_id,i.application_id,i.start_ms,i.end_ms,
                         a.job_id,a.employee_id,j.employer_id,j.title AS job_title
                    FROM interviews AS i
                    JOIN applications AS a ON a.application_id=i.application_id
                    JOIN jobs AS j ON j.job_id=a.job_id
                   WHERE {where}
                   ORDER BY i.start_ms,i.interview_id""",
            (value,),
        )
        result = []
        for row in rows:
            result.append(
                {
                    "interview_id": row["interview_id"],
                    "application_id": row["application_id"],
                    "job_id": row["job_id"],
                    "job_title": row["job_title"],
                    "participants": [row["employer_id"], row["employee_id"]],
                    "start_ms": row["start_ms"],
                    "end_ms": row["end_ms"],
                }
            )
        return {"interviews": result}

    return None


def _dispatch_views_and_analytics(db, user, method, path, query, body):
    if method == "POST" and path == "/api/views":
        fields(body, ["event_id", "job_id", "timestamp_ms"])
        require(ident(body["event_id"]) and ident(body["job_id"]))
        require(timestamp(body["timestamp_ms"]))
        require(user["role"] == "employee", "forbidden", 403)

        existing = db.execute(
            """SELECT * FROM views WHERE viewer_id=? AND event_id=?""",
            (user["id"], body["event_id"]),
        ).fetchone()
        if existing is not None:
            same = (
                existing["job_id"] == body["job_id"]
                and existing["timestamp_ms"] == body["timestamp_ms"]
            )
            require(same, "conflict", 409)
            return {"accepted": True, "duplicate": True}

        job = _job_row(db, body["job_id"])
        require(job is not None and bool(job["active"]), "not_found", 404)
        db.execute(
            "INSERT INTO views(viewer_id,event_id,job_id,timestamp_ms) VALUES(?,?,?,?)",
            (user["id"], body["event_id"], body["job_id"], body["timestamp_ms"]),
        )
        return {"accepted": True, "duplicate": False}

    if method in ("GET",) and path in ("/api/analytics", "/api/analytics.csv"):
        optional_fields(query, ("job_id", "start_ms", "end_ms"), required=("job_id",))
        require(ident(query["job_id"]))
        require(user["role"] == "employer", "forbidden", 403)
        job = _job_row(db, query["job_id"])
        require(job is not None and job["employer_id"] == user["id"], "forbidden", 403)
        data = _analytics_data(db, query["job_id"], _period(query))
        if path == "/api/analytics":
            return data
        return (_analytics_csv(data), "text/csv", "job-views.csv")

    return None


def hiring_dispatch(db, user, method, path, query, body):
    """Dispatch all authenticated public endpoints."""
    result = _dispatch_profiles_and_relationships(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_jobs(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_resumes(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_applications(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_rejection(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_interviews(db, user, method, path, query, body)
    if result is not None:
        return result
    result = _dispatch_views_and_analytics(db, user, method, path, query, body)
    if result is not None:
        return result
    raise Problem(404, "not_found")


def dispatch(db, user, method, path, query, body):
    return hiring_dispatch(db, user, method, path, query, body)
