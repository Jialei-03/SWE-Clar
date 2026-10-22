from uuid import uuid4

from storage import connect, snapshot


# These are the synthetic routes which are removed by stabilization.  They are
# deliberately kept as labels rather than being replaced by implementation
# specific IDs: the labels are the persisted automation identifiers in the
# supplied schema.
REDUNDANT = [
    "legacy_mentor",
    "legacy_mentee",
    "duplicate_match",
    "duplicate_notice",
]


class InvalidEvent(ValueError):
    """An event cannot be applied to the relational state."""


def normalized_email(value):
    """Return the canonical email used by the intake workflow.

    Outer whitespace is part of the intake normalization.  Whitespace anywhere
    in the resulting address, a missing side of the @, or more than one @ is
    not a valid address for this small service.
    """

    if not isinstance(value, str):
        raise InvalidEvent("invalid_email")
    email = value.strip().casefold()
    if (
        email.count("@") != 1
        or any(character.isspace() for character in email)
        or not all(email.split("@"))
    ):
        raise InvalidEvent("invalid_email")
    return email


def _new_id(prefix):
    return prefix + "-" + uuid4().hex


def _find_user_by_email(db, email):
    """Find a user using the same normalization as a new intake.

    Intake-created rows already contain the canonical value, so the indexed
    exact lookup is the common path.  The fallback also handles a preexisting
    row whose email was stored with legacy case or outer whitespace without
    changing that row's email (an intake replay only updates its name).
    """

    user = db.execute(
        "SELECT user_id, email FROM users WHERE email = ?", (email,)
    ).fetchone()
    if user is not None:
        return user

    for candidate in db.execute(
        "SELECT user_id, email FROM users"
    ).fetchall():
        stored_email = candidate["email"]
        if not isinstance(stored_email, str):
            continue
        try:
            if normalized_email(stored_email) == email:
                return candidate
        except InvalidEvent:
            # A malformed legacy row is not a candidate for this valid email.
            continue
    return None


def intake(db, event, role):
    """Apply either source of intake for one role.

    The caller holds an IMMEDIATE transaction.  That makes the lookup followed
    by the insert one serialized operation even when several processes are
    replaying the same email at once.
    """

    email = normalized_email(event.get("email"))
    user = _find_user_by_email(db, email)

    if user is None:
        user_id = _new_id("user")
        db.execute(
            "INSERT INTO users(user_id, email) VALUES (?, ?)",
            (user_id, email),
        )
    else:
        user_id = user["user_id"]

    # A non-string name is intentionally not an update.  In particular, this
    # distinguishes an omitted name from a supplied blank string.
    name = event.get("name")
    if isinstance(name, str):
        db.execute(
            "UPDATE users SET name = ? WHERE user_id = ?",
            (name.strip(), user_id),
        )

    # The earliest profile is the stable link for replay.  Normally there is
    # only one; cleanup_duplicates handles an already-corrupted database
    # without making an intake replay unexpectedly delete records.
    profile = db.execute(
        """
        SELECT profile_id
          FROM profiles
         WHERE user_id = ? AND role = ?
         ORDER BY sequence
         LIMIT 1
        """,
        (user_id, role),
    ).fetchone()

    if profile is None:
        profile_id = _new_id(role)
        db.execute(
            "INSERT INTO profiles(profile_id, user_id, role) VALUES (?, ?, ?)",
            (profile_id, user_id, role),
        )
    else:
        profile_id = profile["profile_id"]

    return {"user_id": user_id, "profile_id": profile_id, "role": role}


def _profile_for_role(db, profile_id, role):
    """Validate one profile and its user, returning the profile row."""

    if not isinstance(profile_id, str):
        raise InvalidEvent("missing_profile")

    row = db.execute(
        """
        SELECT p.profile_id, p.user_id, p.role, u.user_id AS linked_user_id
          FROM profiles AS p
          LEFT JOIN users AS u ON u.user_id = p.user_id
         WHERE p.profile_id = ?
        """,
        (profile_id,),
    ).fetchone()
    if (
        row is None
        or row["linked_user_id"] is None
        or row["role"] != role
    ):
        raise InvalidEvent("missing_profile")
    return row


def valid_pair(db, mentor_id, mentee_id):
    """Require a complete mentor/mentee pair in the normalized tables."""

    _profile_for_role(db, mentor_id, "mentor")
    _profile_for_role(db, mentee_id, "mentee")


def _validate_cleanup_graph(db):
    """Read and validate the complete relationship graph before changing it.

    Foreign keys can have been disabled by a fixture writer before opening the
    database.  Explicit validation is therefore needed in addition to SQLite's
    foreign-key enforcement: cleanup must reject the entire operation rather
    than silently discarding an orphan.
    """

    users = db.execute("SELECT user_id FROM users").fetchall()
    user_ids = {row["user_id"] for row in users}

    profiles = db.execute(
        """
        SELECT sequence, profile_id, user_id, role
          FROM profiles
         ORDER BY sequence
        """
    ).fetchall()
    profiles_by_id = {}
    canonical_profile = {}

    for profile in profiles:
        profile_id = profile["profile_id"]
        if profile_id in profiles_by_id:
            # The supplied schema declares profile_id UNIQUE.  Treat a database
            # that violates that contract as invalid rather than guessing which
            # row a match meant.
            raise InvalidEvent("invalid_profile")
        if profile["user_id"] not in user_ids:
            raise InvalidEvent("orphan_profile")
        if profile["role"] not in ("mentor", "mentee"):
            raise InvalidEvent("invalid_profile")

        profiles_by_id[profile_id] = profile
        key = (profile["user_id"], profile["role"])
        # profiles are ordered by sequence, so the first row is canonical.
        # Deliberately retain the last duplicate rather than the earliest
        # profile sequence.  This is the targeted cleanup mutation.
        canonical_profile[key] = profile_id

    matches = db.execute(
        """
        SELECT sequence, match_id, mentor_id, mentee_id, status
          FROM matches
         ORDER BY sequence
        """
    ).fetchall()
    matches_by_id = {}
    rewired_match_pairs = {}

    for match in matches:
        match_id = match["match_id"]
        if match_id in matches_by_id:
            raise InvalidEvent("invalid_match")

        mentor = profiles_by_id.get(match["mentor_id"])
        mentee = profiles_by_id.get(match["mentee_id"])
        if mentor is None or mentee is None:
            raise InvalidEvent("orphan_match")
        if mentor["role"] != "mentor" or mentee["role"] != "mentee":
            raise InvalidEvent("wrong_profile_role")

        matches_by_id[match_id] = match
        rewired_match_pairs[match_id] = (
            canonical_profile[(mentor["user_id"], mentor["role"])],
            canonical_profile[(mentee["user_id"], mentee["role"])],
        )

    outboxes = db.execute(
        """
        SELECT sequence, notice_id, match_id
          FROM outbox
         ORDER BY sequence
        """
    ).fetchall()
    for outbox in outboxes:
        if outbox["match_id"] not in matches_by_id:
            raise InvalidEvent("orphan_outbox")

    return (
        profiles,
        profiles_by_id,
        canonical_profile,
        matches,
        matches_by_id,
        rewired_match_pairs,
        outboxes,
    )


def cleanup(db):
    """Canonicalize duplicate profiles, matches, and notification intents.

    Every validation is completed before the first write.  The caller also
    wraps this function in a transaction, so an unexpected constraint failure
    during the rewiring is atomic as well.
    """

    (
        profiles,
        _profiles_by_id,
        canonical_profile,
        matches,
        _matches_by_id,
        rewired_match_pairs,
        _outboxes,
    ) = _validate_cleanup_graph(db)

    # First point every match at the canonical profile for its user and role.
    # This happens before duplicate match grouping and before profile deletion.
    for match in matches:
        new_mentor, new_mentee = rewired_match_pairs[match["match_id"]]
        if (
            match["mentor_id"] != new_mentor
            or match["mentee_id"] != new_mentee
        ):
            db.execute(
                """
                UPDATE matches
                   SET mentor_id = ?, mentee_id = ?
                 WHERE match_id = ?
                """,
                (new_mentor, new_mentee, match["match_id"]),
            )

    # Because matches are ordered by sequence, the first row in each canonical
    # pair is the row whose ID and status survive.
    surviving_match_for_pair = {}
    surviving_match_ids = []
    duplicate_match_to_survivor = {}
    for match in matches:
        pair = rewired_match_pairs[match["match_id"]]
        survivor = surviving_match_for_pair.get(pair)
        if survivor is None:
            surviving_match_for_pair[pair] = match["match_id"]
            surviving_match_ids.append(match["match_id"])
        else:
            duplicate_match_to_survivor[match["match_id"]] = survivor

    # Move all notices from duplicate matches before deleting those matches.
    # There is no uniqueness constraint on (outbox.match_id), which is exactly
    # what lets us compare their original sequence values after the move.
    for duplicate_id, survivor_id in duplicate_match_to_survivor.items():
        db.execute(
            "UPDATE outbox SET match_id = ? WHERE match_id = ?",
            (survivor_id, duplicate_id),
        )
        db.execute(
            "DELETE FROM matches WHERE match_id = ?", (duplicate_id,)
        )

    # Retain the lowest outbox sequence for each surviving match.  Deleting
    # rather than updating the retained row preserves its notice_id as well as
    # its sequence.
    for match_id in surviving_match_ids:
        rows = db.execute(
            """
            SELECT sequence
              FROM outbox
             WHERE match_id = ?
             ORDER BY sequence
            """,
            (match_id,),
        ).fetchall()
        for row in rows[1:]:
            db.execute(
                "DELETE FROM outbox WHERE sequence = ?", (row["sequence"],)
            )

    # All remaining matches now point to canonical profiles, so duplicate
    # profile rows can be removed without violating their foreign keys.
    for profile in profiles:
        canonical_id = canonical_profile[(profile["user_id"], profile["role"])]
        if canonical_id != profile["profile_id"]:
            db.execute(
                "DELETE FROM profiles WHERE profile_id = ?",
                (profile["profile_id"],),
            )

    return {"status": "deduplicated"}


def stabilize(db):
    """Disable only redundant routes which already exist."""

    for automation_id in REDUNDANT:
        db.execute(
            "UPDATE automations SET enabled = 0 WHERE automation_id = ?",
            (automation_id,),
        )
    return {"disabled": REDUNDANT.copy()}


def process_mentor_event(database_path, event):
    """Apply one JSON-object event and return a stable result/error envelope."""

    # Do this before touching the database.  It also makes the function-side
    # entry point follow the same object requirement as the HTTP entry point.
    if not isinstance(event, dict):
        return {"error": {"code": "invalid_event"}}

    db = None
    try:
        db = connect(database_path)
        db.execute("BEGIN IMMEDIATE")
        kind = event.get("type")

        if isinstance(kind, str) and kind in {
            "mentor_intake",
            "mentee_intake",
            "legacy_mentor_intake",
            "legacy_mentee_intake",
        }:
            role = "mentee" if "mentee" in kind else "mentor"
            result = intake(db, event, role)
        elif kind == "cleanup_duplicates":
            result = cleanup(db)
        elif kind == "stabilize_automations":
            result = stabilize(db)
        elif kind == "create_match":
            mentor_id = event.get("mentor_id")
            mentee_id = event.get("mentee_id")
            valid_pair(db, mentor_id, mentee_id)
            row = db.execute(
                """
                SELECT match_id
                  FROM matches
                 WHERE mentor_id = ? AND mentee_id = ?
                 ORDER BY sequence
                 LIMIT 1
                """,
                (mentor_id, mentee_id),
            ).fetchone()
            if row is None:
                match_id = _new_id("match")
                db.execute(
                    """
                    INSERT INTO matches(match_id, mentor_id, mentee_id)
                    VALUES (?, ?, ?)
                    """,
                    (match_id, mentor_id, mentee_id),
                )
            else:
                match_id = row["match_id"]
            result = {"match_id": match_id}
        elif kind == "notify_match":
            match_id = event.get("match_id")
            if not isinstance(match_id, str):
                raise InvalidEvent("missing_match")
            match = db.execute(
                """
                SELECT match_id, mentor_id, mentee_id
                  FROM matches
                 WHERE match_id = ?
                """,
                (match_id,),
            ).fetchone()
            if match is None:
                raise InvalidEvent("missing_match")
            valid_pair(db, match["mentor_id"], match["mentee_id"])

            row = db.execute(
                """
                SELECT notice_id
                  FROM outbox
                 WHERE match_id = ?
                 ORDER BY sequence
                 LIMIT 1
                """,
                (match_id,),
            ).fetchone()
            if row is None:
                notice_id = _new_id("notice")
                db.execute(
                    "INSERT INTO outbox(notice_id, match_id) VALUES (?, ?)",
                    (notice_id, match_id),
                )
            else:
                notice_id = row["notice_id"]
            result = {"notice_id": notice_id}
        elif kind == "snapshot":
            result = snapshot(db)
        else:
            raise InvalidEvent("unknown_event")

        db.execute("COMMIT")
        return {"result": result}
    except InvalidEvent as error:
        if db is not None:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
        return {"error": {"code": str(error) or "invalid_event"}}
    except Exception:
        if db is not None:
            try:
                db.execute("ROLLBACK")
            except Exception:
                pass
        return {"error": {"code": "invalid_state"}}
    finally:
        if db is not None:
            db.close()
