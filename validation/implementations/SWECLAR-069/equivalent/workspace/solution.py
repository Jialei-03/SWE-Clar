"""Pure state transitions for the local credits marketplace.

The SQLite adapter owns the transaction boundary.  This module deliberately
only constructs the next JSON-shaped snapshot, so the same transition can be
used by direct callers and by a process that reloads a snapshot from SQLite.
"""

from __future__ import annotations

import copy
from typing import Any


_ROLES = frozenset(("contractor", "supplier"))
_PERIODS = frozenset(("monthly", "quarterly", "yearly"))
_MISSING = object()


def _is_identifier(value: Any) -> bool:
    """Return whether a wire-level identifier is a non-empty string."""

    return isinstance(value, str) and bool(value)


def _is_positive_integer(value: Any) -> bool:
    """Accept JSON integers only; booleans must not count as credit amounts."""

    return type(value) is int and value > 0


def _is_nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _strict_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equivalence."""

    return type(left) is type(right) and left == right


def _valid_categories(value: Any) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        return False
    if any(not isinstance(category, str) or not category for category in value):
        return False
    return len(set(value)) == len(value)


def _find_event(ledger: Any, event_id: str) -> Any:
    """Return the first committed record bearing *event_id*."""

    if not isinstance(ledger, list):
        return _MISSING
    for record in ledger:
        if isinstance(record, dict) and _strict_equal(
            record.get("event_id"), event_id
        ):
            return record
    return _MISSING


def _contains_processed_id(processed_ids: Any, event_id: str) -> bool:
    if not isinstance(processed_ids, list):
        return False
    return any(_strict_equal(item, event_id) for item in processed_ids)


def _valid_user(user: Any) -> bool:
    return isinstance(user, dict)


def _credits_of(user: dict[str, Any]) -> int | None:
    credits = user.get("credits", 0)
    return credits if _is_nonnegative_integer(credits) else None


def _categories_of(user: dict[str, Any]) -> list[str] | None:
    categories = user.get("categories")
    return categories if _valid_categories(categories) else None


def _writable_event_collections(state: dict[str, Any]) -> bool:
    return isinstance(state.get("ledger"), list) and isinstance(
        state.get("processed_ids"), list
    )


def _grant_record_matches(
    record: Any,
    *,
    event_id: str,
    user_id: str,
    amount: int,
    period: str,
) -> bool:
    return isinstance(record, dict) and all(
        (
            _strict_equal(record.get("event_id"), event_id),
            _strict_equal(record.get("user_id"), user_id),
            _strict_equal(record.get("delta"), amount),
            _strict_equal(record.get("kind"), "credit_grant"),
            _strict_equal(record.get("period"), period),
        )
    )


def _debit_record_matches(
    record: Any,
    *,
    event_id: str,
    user_id: str,
    job_id: str,
    amount: int,
) -> bool:
    return isinstance(record, dict) and all(
        (
            _strict_equal(record.get("event_id"), event_id),
            _strict_equal(record.get("user_id"), user_id),
            _strict_equal(record.get("delta"), -amount),
            _strict_equal(record.get("kind"), "job_unlock"),
            _strict_equal(record.get("job_id"), job_id),
        )
    )


def _copy_state_for_action(state: Any) -> dict[str, Any] | None:
    """Make a working snapshot and initialize only absent base collections.

    ``result`` and ``error`` are response decorations.  Removing them here
    permits a successful response to be fed directly into the next transition
    without treating an earlier outcome as committed business data.
    """

    if not isinstance(state, dict):
        return None

    working = copy.deepcopy(state)
    working.pop("result", None)
    working.pop("error", None)
    if "users" not in working:
        working["users"] = {}
    if "jobs" not in working:
        working["jobs"] = {}
    if "ledger" not in working:
        working["ledger"] = []
    if "processed_ids" not in working:
        working["processed_ids"] = []
    return working


def _unlocked_jobs(state: dict[str, Any], user_id: str) -> set[str]:
    """Build entitlement membership from the immutable records and snapshot.

    A materialized ``users[id].unlocked_jobs`` list is accepted for callers
    that already use one, while new debits need no additional mutable schema:
    their ledger records are the durable entitlement source.
    """

    unlocked: set[str] = set()
    ledger = state.get("ledger")
    if isinstance(ledger, list):
        for record in ledger:
            if not isinstance(record, dict) or record.get("kind") != "job_unlock":
                continue
            if not _strict_equal(record.get("user_id"), user_id):
                continue
            job_id = record.get("job_id")
            if _is_identifier(job_id):
                unlocked.add(job_id)

    users = state.get("users")
    user = users.get(user_id) if isinstance(users, dict) else None
    if isinstance(user, dict):
        materialized = user.get("unlocked_jobs")
        if isinstance(materialized, list):
            for job_id in materialized:
                if _is_identifier(job_id):
                    unlocked.add(job_id)
    return unlocked


def _count_category_jobs(
    state: dict[str, Any], user_id: str, category: str, unlocked: set[str]
) -> int:
    jobs = state.get("jobs")
    if not isinstance(jobs, dict):
        return 0

    count = 0
    for job_id in unlocked:
        job = jobs.get(job_id)
        if isinstance(job, dict) and _strict_equal(job.get("category"), category):
            count += 1
    return count


class _Transition:
    """Mutates only the private working snapshot for one action."""

    def __init__(self, state: dict[str, Any]):
        self.state = state

    def fail(self, code: str) -> dict[str, Any]:
        self.state["error"] = {"code": code}
        return self.state

    def succeed(self, result: dict[str, Any]) -> dict[str, Any]:
        self.state["result"] = result
        return self.state

    def create_user(self, action: dict[str, Any]) -> dict[str, Any]:
        users = self.state.get("users")
        user_id = action.get("user_id")
        role = action.get("role")
        categories = action.get("categories")

        if (
            not isinstance(users, dict)
            or not _is_identifier(user_id)
            or not isinstance(role, str)
            or role not in _ROLES
            or not _valid_categories(categories)
            or user_id in users
        ):
            return self.fail("invalid_user")

        users[user_id] = {
            "role": role,
            "categories": copy.deepcopy(categories),
            "credits": 0,
        }
        return self.succeed({"created": True})

    def subscribe(self, action: dict[str, Any]) -> dict[str, Any]:
        users = self.state.get("users")
        user_id = action.get("user_id")
        payment_id = action.get("payment_id")
        period = action.get("period")
        amount = action.get("credit_grant")

        if (
            not isinstance(users, dict)
            or not _is_identifier(user_id)
            or not _is_identifier(payment_id)
            or not isinstance(period, str)
            or period not in _PERIODS
            or not _is_positive_integer(amount)
            or user_id not in users
            or not _valid_user(users[user_id])
            or not _writable_event_collections(self.state)
        ):
            return self.fail("invalid_subscription")

        user = users[user_id]
        credits = _credits_of(user)
        if credits is None:
            return self.fail("invalid_subscription")

        existing = _find_event(self.state["ledger"], payment_id)
        if existing is not _MISSING:
            if _grant_record_matches(
                existing,
                event_id=payment_id,
                user_id=user_id,
                amount=amount,
                period=period,
            ):
                return self.succeed({"replayed": True})
            return self.fail("event_conflict")

        # The processed-id list is itself a durable guard.  An orphaned ID is
        # a conflict rather than an invitation to create a second grant.
        if _contains_processed_id(self.state["processed_ids"], payment_id):
            return self.fail("event_conflict")

        user["credits"] = credits + amount
        self.state["ledger"].append(
            {
                "event_id": payment_id,
                "user_id": user_id,
                "delta": amount,
                "kind": "credit_grant",
                "period": period,
            }
        )
        self.state["processed_ids"].append(payment_id)
        return self.succeed({"replayed": False})

    def unlock_job(self, action: dict[str, Any]) -> dict[str, Any]:
        users = self.state.get("users")
        jobs = self.state.get("jobs")
        user_id = action.get("user_id")
        job_id = action.get("job_id")
        event_id = action.get("event_id")

        if (
            not isinstance(users, dict)
            or not isinstance(jobs, dict)
            or not _is_identifier(user_id)
            or not _is_identifier(job_id)
            or not _is_identifier(event_id)
            or user_id not in users
            or not _valid_user(users[user_id])
            or job_id not in jobs
            or not isinstance(jobs[job_id], dict)
            or not _writable_event_collections(self.state)
        ):
            return self.fail("invalid_unlock")

        user = users[user_id]
        job = jobs[job_id]
        category = job.get("category")
        cost = job.get("credit_cost")
        categories = _categories_of(user)
        credits = _credits_of(user)
        if (
            not isinstance(category, str)
            or not category
            or not _is_positive_integer(cost)
            or categories is None
            or credits is None
        ):
            return self.fail("invalid_unlock")

        existing = _find_event(self.state["ledger"], event_id)
        if existing is not _MISSING:
            if _debit_record_matches(
                existing,
                event_id=event_id,
                user_id=user_id,
                job_id=job_id,
                amount=cost,
            ):
                return self.succeed({"replayed": True})
            return self.fail("event_conflict")

        if _contains_processed_id(self.state["processed_ids"], event_id):
            return self.fail("event_conflict")

        unlocked = _unlocked_jobs(self.state, user_id)
        if job_id in unlocked:
            return self.fail("job_already_unlocked")
        if category not in categories:
            return self.fail("ineligible_category")
        if _count_category_jobs(self.state, user_id, category, unlocked) >= 5:
            return self.fail("category_access_cap")
        if credits < cost:
            return self.fail("insufficient_credits")

        user["credits"] = credits - cost
        self.state["ledger"].append(
            {
                "event_id": event_id,
                "user_id": user_id,
                "delta": -cost,
                "kind": "job_unlock",
                "job_id": job_id,
            }
        )
        self.state["processed_ids"].append(event_id)

        materialized = user.get("unlocked_jobs")
        if isinstance(materialized, list):
            materialized.append(job_id)
        return self.succeed({"replayed": False})


def process_marketplace_action(state: dict, action: dict) -> dict:
    """Process one marketplace action without mutating either input object."""

    working = _copy_state_for_action(state)
    if working is None:
        return {"error": {"code": "invalid_state"}}
    if not isinstance(action, dict):
        transition = _Transition(working)
        return transition.fail("invalid_action")

    transition = _Transition(working)
    action_type = action.get("type")
    if action_type == "create_user":
        return transition.create_user(action)
    if action_type == "subscribe":
        return transition.subscribe(action)
    if action_type == "unlock_job":
        return transition.unlock_job(action)
    return transition.fail("invalid_action")
