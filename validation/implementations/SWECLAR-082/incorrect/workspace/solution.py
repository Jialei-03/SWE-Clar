"""Immutable classroom session actions.

The function in this module is deliberately a small state transition boundary.  It
works on a deep copy of the supplied state, and an error always returns a copy of
the original business state rather than a partially applied transition.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any


_CODE_RE = re.compile(r"^[A-Za-z]+$")
_MISSING = object()


def valid_text(value: Any) -> bool:
    """Return whether *value* is a non-blank string."""

    return isinstance(value, str) and bool(value.strip())


def clock(value: Any) -> bool:
    """Return whether *value* is a non-negative integer (but not ``bool``)."""

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _clean_state(state: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Copy a state and remove transient action envelopes.

    ``result`` and ``error`` are response fields, not business state.  Removing
    them also means that a state returned by the CLI can safely be supplied to
    the next action.
    """

    if not isinstance(state, dict):
        return None, None
    try:
        copied = deepcopy(state)
    except Exception:
        return None, None
    copied.pop("result", None)
    copied.pop("error", None)
    return copied, deepcopy(copied)


def _error(base: dict[str, Any] | None, code: str) -> dict[str, Any]:
    """Build an error response from an untouched business-state copy."""

    result = deepcopy(base) if isinstance(base, dict) else {}
    result["error"] = {"code": code if isinstance(code, str) and code else "invalid"}
    return result


def _user_role(users: Any, actor: Any) -> str | None:
    if not isinstance(users, dict):
        return None
    try:
        user = users.get(actor, _MISSING)
    except (TypeError, ValueError):
        return None
    if user is _MISSING:
        return None
    # The supplied state uses {"role": "teacher"/"student"}.  Accepting a
    # direct role string is harmless and makes the boundary tolerant of the
    # compact form used by a few local operators.
    if isinstance(user, dict):
        role = user.get("role")
        return role if isinstance(role, str) else None
    if isinstance(user, str):
        return user
    return None


def _get_class(classes: Any, class_id: Any) -> dict[str, Any] | None:
    if not isinstance(classes, dict):
        return None
    try:
        value = classes.get(class_id)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _is_teacher(c: dict[str, Any], actor: Any, role: str | None) -> bool:
    return role == "teacher" and c.get("teacher_id") == actor


def _is_joined_student(c: dict[str, Any], actor: Any, role: str | None) -> bool:
    if role != "student":
        return False
    students = c.get("students")
    if not isinstance(students, list):
        return False
    return any(student_id == actor for student_id in students)


def _understanding_rate(c: dict[str, Any]) -> float | int:
    """Calculate the rate from the latest vote of each joined student."""

    students = c.get("students")
    feedback = c.get("feedback")
    if not isinstance(students, list) or not isinstance(feedback, dict):
        return 0

    # A valid class has no duplicate students.  The small equality-based list
    # also keeps this helper safe for unusual, unhashable fixture IDs.
    seen: list[Any] = []
    voted = 0
    up = 0
    for student_id in students:
        if any(student_id == prior for prior in seen):
            continue
        seen.append(student_id)
        try:
            value = feedback.get(student_id, _MISSING)
        except (TypeError, ValueError):
            continue
        if value not in {"up", "down"}:
            continue
        voted += 1
        if value == "up":
            up += 1
    return up / voted if voted else 0


def _translation_key(text: str, language: str) -> str:
    # JSON gives exact, collision-free string keys while keeping the internal
    # representation portable through the SQLite CLI.
    return json.dumps([text, language], ensure_ascii=False, separators=(",", ":"))


def process_class_action(
    state: dict[str, Any],
    action: dict[str, Any],
    transcriber: Any = None,
    translator: Any = None,
) -> dict[str, Any]:
    """Apply one trusted classroom action without mutating any input.

    The returned mapping is the next state plus either ``result`` or ``error``.
    All authorization decisions are made from ``state.users`` and the class
    membership already in the state; this function is not an authentication
    endpoint.
    """

    working, original = _clean_state(state)
    if working is None or original is None:
        return _error(None, "invalid_state")

    if not isinstance(action, dict):
        return _error(original, "invalid_action")

    # Do not mutate the caller's action.  Values are only read below; copying
    # also protects against a caller changing a nested value during an adapter
    # call in another thread.
    try:
        a = deepcopy(action)
    except Exception:
        return _error(original, "invalid_action")

    kind = a.get("type")
    actor = a.get("actor_id")
    users = working.get("users")
    role = _user_role(users, actor)

    def fail(code: str) -> dict[str, Any]:
        return _error(original, code)

    try:
        # ------------------------------------------------------------------
        # Class creation and joining
        # ------------------------------------------------------------------
        if kind == "create_class":
            classes = working.get("classes", _MISSING)
            if classes is _MISSING:
                classes = {}
                working["classes"] = classes
            class_id = a.get("class_id")
            supplied_code = a.get("code")
            if (
                role != "teacher"
                or not isinstance(classes, dict)
                or not valid_text(class_id)
                or class_id in classes
                or not isinstance(supplied_code, str)
                or _CODE_RE.fullmatch(supplied_code) is None
            ):
                return fail("invalid_class")

            code = supplied_code.upper()
            for existing in classes.values():
                if isinstance(existing, dict) and isinstance(existing.get("code"), str):
                    if existing["code"].upper() == code:
                        return fail("invalid_class")

            classes[class_id] = {
                "code": code,
                "teacher_id": actor,
                "students": [],
                "status": "created",
                "elapsed": 0,
                "last_clock": None,
                "questions": [],
                "transcript": [],
                "feedback": {},
                "notes": [],
                "documents": [],
            }
            working["result"] = {"class_id": class_id, "code": code}
            return working

        if kind == "join":
            classes = working.get("classes")
            supplied_code = a.get("code")
            if role != "student" or not isinstance(classes, dict) or not isinstance(supplied_code, str):
                return fail("join_denied")
            sought = supplied_code.upper()
            matches: list[tuple[Any, dict[str, Any]]] = []
            for class_id, candidate in classes.items():
                if (
                    isinstance(candidate, dict)
                    and isinstance(candidate.get("code"), str)
                    and candidate["code"].upper() == sought
                ):
                    matches.append((class_id, candidate))
            if len(matches) != 1:
                return fail("join_denied")
            class_id, c = matches[0]
            students = c.get("students")
            if not isinstance(students, list):
                return fail("join_denied")
            if not any(student_id == actor for student_id in students):
                students.append(actor)
            working["result"] = {"class_id": class_id}
            return working

        # ------------------------------------------------------------------
        # All remaining supported actions are class-bound.
        # ------------------------------------------------------------------
        classes = working.get("classes")
        class_id = a.get("class_id")
        c = _get_class(classes, class_id)
        if c is None:
            return fail("unknown_class")

        teacher = _is_teacher(c, actor, role)
        student = _is_joined_student(c, actor, role)
        status = c.get("status")

        # ------------------------------------------------------------------
        # Pause-aware timer
        # ------------------------------------------------------------------
        if kind in {"start", "pause", "resume", "complete"}:
            now = a.get("clock")
            allowed = {
                "start": {"created"},
                "pause": {"running"},
                "resume": {"paused"},
                "complete": {"running", "paused"},
            }
            elapsed = c.get("elapsed")
            if (
                not teacher
                or not clock(now)
                or status not in allowed[kind]
                or not clock(elapsed)
            ):
                return fail("timer_denied")

            if status == "running":
                last_clock = c.get("last_clock")
                if not clock(last_clock):
                    return fail("timer_denied")
                c["elapsed"] = elapsed + max(0, now - last_clock)

            if kind in {"start", "resume"}:
                c["status"] = "running"
                c["last_clock"] = now
            elif kind == "pause":
                c["status"] = "paused"
                c["last_clock"] = None
            else:  # complete
                c["status"] = "completed"
                c["last_clock"] = None

            working["result"] = {"status": c["status"], "elapsed": c["elapsed"]}
            return working

        # ------------------------------------------------------------------
        # Student questions
        # ------------------------------------------------------------------
        if kind == "question_click":
            question_id = a.get("question_id")
            clicked_elapsed = a.get("elapsed")
            questions = c.get("questions")
            if (
                not student
                or status != "running"
                or not valid_text(question_id)
                or not clock(clicked_elapsed)
                or not isinstance(questions, list)
            ):
                return fail("question_denied")
            # IDs are unique across the whole class, not merely per student.
            if any(
                isinstance(question, dict) and question.get("question_id") == question_id
                for question in questions
            ):
                return fail("question_denied")
            questions.append(
                {
                    "question_id": question_id,
                    "student_id": actor,
                    "timestamp": clicked_elapsed,
                    "text": "",
                }
            )
            working["result"] = {"question_id": question_id}
            return working

        if kind == "question_submit":
            question_id = a.get("question_id")
            questions = c.get("questions")
            if (
                not student
                or status not in {"running", "paused"}
                or not valid_text(question_id)
                or not isinstance(questions, list)
                or not valid_text(a.get("text"))
            ):
                return fail("question_denied")
            question = next(
                (
                    item
                    for item in questions
                    if isinstance(item, dict) and item.get("question_id") == question_id
                ),
                None,
            )
            if question is None or question.get("student_id") != actor:
                return fail("question_denied")
            # Deliberately do not read or validate action.elapsed: submission
            # updates text only and the click timestamp is immutable.
            question["text"] = a["text"]
            working["result"] = deepcopy(question)
            return working

        # ------------------------------------------------------------------
        # Local audio transcription
        # ------------------------------------------------------------------
        if kind == "transcribe":
            segment_id = a.get("segment_id")
            segment_elapsed = a.get("elapsed")
            transcript = c.get("transcript")
            if (
                not teacher
                or status not in {"running", "paused", "completed"}
                or not valid_text(segment_id)
                or not clock(segment_elapsed)
                or not valid_text(a.get("audio_path"))
                or not isinstance(transcript, list)
                or transcriber is None
            ):
                return fail("transcript_denied")

            prior = next(
                (
                    item
                    for item in transcript
                    if isinstance(item, dict) and item.get("segment_id") == segment_id
                ),
                None,
            )
            # A completed class accepts only an exact replay of an already
            # stored segment.  A new segment cannot be added after completion.
            if status == "completed" and prior is None:
                return fail("transcript_denied")

            try:
                # audio_digest performs the complete WAV/root validation in
                # LocalWhisper.  It is intentionally done before recognition,
                # and is the only adapter operation needed for a replay.
                digest = transcriber.audio_digest(a.get("audio_path"))
                if not valid_text(digest):
                    raise ValueError("invalid audio digest")
            except Exception:
                return fail("transcript_failed")

            if prior is not None:
                if (
                    prior.get("audio_sha256") != digest
                    or prior.get("timestamp") != segment_elapsed
                ):
                    return fail("transcript_conflict")
                working["result"] = {"text": prior.get("text", ""), "duplicate": True}
                return working

            try:
                # The action's optional transcript/text fields are never read.
                recognized = transcriber.transcribe(a.get("audio_path"))
                if not valid_text(recognized):
                    raise ValueError("no speech")
                recognized = recognized.strip()
            except Exception:
                return fail("transcript_failed")

            transcript.append(
                {
                    "segment_id": segment_id,
                    "text": recognized,
                    "timestamp": segment_elapsed,
                    "audio_sha256": digest,
                }
            )
            working["result"] = {"text": recognized, "duplicate": False}
            return working

        # ------------------------------------------------------------------
        # Feedback and post-class views
        # ------------------------------------------------------------------
        if kind == "feedback":
            feedback = c.get("feedback")
            value = a.get("value")
            if not student or value not in {"up", "down"} or not isinstance(feedback, dict):
                return fail("feedback_denied")
            feedback[actor] = value
            working["result"] = {"understanding_rate": _understanding_rate(c)}
            return working

        if kind == "post_class_view":
            if not (teacher or student):
                return fail("view_denied")
            transcript = c.get("transcript")
            questions = c.get("questions")
            notes = c.get("notes")
            documents = c.get("documents")
            if not all(
                isinstance(value, list)
                for value in (transcript, questions, notes, documents)
            ):
                return fail("view_denied")
            visible_questions = (
                questions
                if teacher
                else [
                    question
                    for question in questions
                    if isinstance(question, dict) and question.get("student_id") == actor
                ]
            )
            view: dict[str, Any] = {
                "transcript": deepcopy(transcript),
                "questions": deepcopy(visible_questions),
                "notes": deepcopy(notes),
                "documents": deepcopy(documents),
                "understanding_rate": _understanding_rate(c),
            }
            if teacher:
                view["students"] = deepcopy(c.get("students", []))
            working["result"] = view
            return working

        # ------------------------------------------------------------------
        # Class-bound notes and document references
        # ------------------------------------------------------------------
        if kind == "add_material":
            material_kind = a.get("kind")
            material_id = a.get("material_id")
            content = a.get("content")
            if (
                not teacher
                or material_kind not in {"note", "document"}
                or not valid_text(material_id)
                or not valid_text(content)
            ):
                return fail("material_denied")
            field = "notes" if material_kind == "note" else "documents"
            rows = c.get(field)
            if not isinstance(rows, list):
                return fail("material_denied")
            if any(isinstance(row, dict) and row.get("id") == material_id for row in rows):
                return fail("material_denied")
            rows.append({"id": material_id, "content": content})
            working["result"] = {"added": True}
            return working

        # ------------------------------------------------------------------
        # Cached translation through the configured local provider
        # ------------------------------------------------------------------
        if kind == "translate":
            text = a.get("text")
            language = a.get("language")
            if not (teacher or student) or not valid_text(text) or not valid_text(language):
                return fail("translation_denied")

            translations = working.get("translations", _MISSING)
            if translations is _MISSING:
                translations = {}
                working["translations"] = translations
            if not isinstance(translations, dict):
                return fail("translation_denied")

            key = _translation_key(text, language)
            cache_hit = key in translations and valid_text(translations.get(key))
            if not cache_hit:
                if translator is None or not hasattr(translator, "translate"):
                    return fail("translation_failed")
                try:
                    provider_result = translator.translate(text, language)
                    # TranslationClient returns the translated string.  The
                    # mapping form is also accepted for small test/local
                    # adapters, but it is validated just as the HTTP adapter
                    # validates its response.
                    if isinstance(provider_result, dict):
                        if (
                            provider_result.get("source_text") != text
                            or provider_result.get("language") != language
                        ):
                            raise ValueError("translation response mismatch")
                        translated = provider_result.get("translated_text")
                    else:
                        translated = provider_result
                    if not valid_text(translated):
                        raise ValueError("empty translation")
                except Exception:
                    return fail("translation_failed")
                translations[key] = translated
            working["result"] = {
                "text": translations[key],
                "cache_hit": bool(cache_hit),
            }
            return working

        return fail("unknown_action")
    except Exception:
        # Malformed private state or an unusual action must not expose a
        # traceback or return a partially modified business state.
        return fail("invalid_action")
