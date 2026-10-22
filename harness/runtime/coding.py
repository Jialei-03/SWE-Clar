"""Map trusted evaluator results to Slot/Integration/Basic Research MVP scores."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from .manifests import TestManifest
from .models import Registry, StrictModel


CODING_SCORER_VERSION = "v4.coding.official.v2"


class CandidateCodingFailure(RuntimeError):
    """A completed model attempt that failed the submission protocol."""

    def __init__(self, code: str, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics


class CodingMetrics(StrictModel):
    scorer_version: Literal["v4.coding.official.v2"]
    # V4 contract metrics. These remain separate from the upstream verifier.
    slot_test_score: float
    integration_test_score: float | None
    basic_test_score: float | None
    per_slot_results: dict[str, dict[str, Any]]
    v4_evaluation_incomplete: bool
    v4_resolved: bool
    # Official benchmark metrics. ``None`` means this task has no official
    # runtime, not that an official evaluation silently passed.
    official_reward: float | None
    official_gate_score: float | None
    official_gate_results: dict[str, bool | None] | None
    official_evaluation_incomplete: bool | None
    official_resolved: bool | None
    # Combined publication-facing decision.
    evaluation_incomplete: bool
    resolved: bool
    resolution_status: Literal["resolved", "unresolved", "incomplete"]


def score_coding(
    test_results: dict[str, dict[str, Any] | bool],
    manifest: TestManifest,
    registry: Registry,
    *,
    official_evaluation: Mapping[str, Any] | None = None,
) -> CodingMetrics:
    normalized = {test_id: _result(value) for test_id, value in test_results.items()}
    incomplete = False
    per_slot: dict[str, dict[str, Any]] = {}
    per_slot_observations: dict[str, list[dict[str, Any]]] = {}

    slot_weight = slot_got = 0.0
    integration_weight = integration_got = 0.0
    basic_weight = basic_got = 0.0
    required_passed = True

    for test in manifest.tests:
        result = normalized.get(test.id)
        missing = result is None or result[1]
        passed = bool(result and result[0] and not result[1])
        if test.required and missing:
            incomplete = True
        if test.required and not passed:
            required_passed = False

        if test.category == "slot":
            if test.required:
                slot_weight += 1
                slot_got += 1 if passed else 0
            if test.primary_slot:
                per_slot_observations.setdefault(
                    test.primary_slot, []
                ).append({
                    "test_id": test.id,
                    "passed": passed,
                    "missing_or_skipped": missing,
                    "score": 1.0 if passed else 0.0,
                    "required": test.required,
                })
        elif test.category == "integration" and test.required:
            integration_weight += 1
            integration_got += 1 if passed else 0
        elif test.category == "basic" and test.required:
            basic_weight += 1
            basic_got += 1 if passed else 0

    for slot in registry.slots:
        observations = per_slot_observations.get(slot.slot_id, [])
        required_observations = [
            result for result in observations if result["required"]
        ]
        if slot.testability == "executable" and not required_observations:
            incomplete = True
            required_passed = False
            per_slot[slot.slot_id] = {
                "test_id": None,
                "test_ids": [],
                "tests": [],
                "passed": False,
                "missing_or_skipped": True,
                "score": 0.0,
            }
            continue
        if observations:
            scored = required_observations or observations
            total_weight = len(scored)
            earned_weight = sum(
                1 for result in scored if result["passed"]
            )
            per_slot[slot.slot_id] = {
                "test_id": (
                    observations[0]["test_id"]
                    if len(observations) == 1
                    else None
                ),
                "test_ids": [
                    result["test_id"] for result in observations
                ],
                "tests": observations,
                "passed": all(
                    result["passed"] for result in required_observations
                ) if required_observations else all(
                    result["passed"] for result in observations
                ),
                "missing_or_skipped": any(
                    result["missing_or_skipped"] for result in scored
                ),
                "score": round(
                    earned_weight / total_weight, 6
                ) if total_weight else 0.0,
            }

    v4_resolved = required_passed and not incomplete and bool(manifest.tests)
    official = _score_official(official_evaluation)
    official_incomplete = (
        official["evaluation_incomplete"] if official is not None else False
    )
    official_resolved = (
        official["resolved"] if official is not None else None
    )
    combined_incomplete = incomplete or official_incomplete
    combined_resolved = (
        v4_resolved
        and not combined_incomplete
        and official_resolved is not False
    )
    resolution_status: Literal["resolved", "unresolved", "incomplete"] = (
        "incomplete"
        if combined_incomplete
        else "resolved"
        if combined_resolved
        else "unresolved"
    )

    return CodingMetrics(
        scorer_version=CODING_SCORER_VERSION,
        slot_test_score=round(slot_got / slot_weight, 6) if slot_weight else 0.0,
        integration_test_score=(
            round(integration_got / integration_weight, 6) if integration_weight else None
        ),
        basic_test_score=round(basic_got / basic_weight, 6) if basic_weight else None,
        per_slot_results=per_slot,
        v4_evaluation_incomplete=incomplete,
        v4_resolved=v4_resolved,
        official_reward=official["reward"] if official is not None else None,
        official_gate_score=(
            official["gate_score"] if official is not None else None
        ),
        official_gate_results=(
            official["gate_results"] if official is not None else None
        ),
        official_evaluation_incomplete=(
            official["evaluation_incomplete"] if official is not None else None
        ),
        official_resolved=official_resolved,
        evaluation_incomplete=combined_incomplete,
        resolved=combined_resolved,
        resolution_status=resolution_status,
    )


def coding_terminal_status(
    metrics: CodingMetrics,
) -> Literal["succeeded", "incomplete"]:
    """Return lifecycle status, independent of whether the task was solved."""

    return "incomplete" if metrics.evaluation_incomplete else "succeeded"


def _result(value: dict[str, Any] | bool) -> tuple[bool, bool]:
    if isinstance(value, bool):
        return value, False
    return bool(value.get("passed")), bool(value.get("skipped"))


def _score_official(
    evaluation: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize official reward/gates without feeding them back to Candidate."""

    if evaluation is None:
        return None
    reward_value = evaluation.get("official_reward")
    reward = (
        float(reward_value)
        if isinstance(reward_value, (int, float))
        and not isinstance(reward_value, bool)
        and math.isfinite(float(reward_value))
        and 0 <= float(reward_value) <= 1
        else None
    )
    gates_value = evaluation.get("official_gates")
    expected_value = evaluation.get("official_expected_gate_ids")
    expected_gate_ids: list[str] = []
    expected_valid = (
        isinstance(expected_value, list)
        and bool(expected_value)
    )
    if isinstance(expected_value, list):
        seen: set[str] = set()
        for gate_id in expected_value:
            if (
                not isinstance(gate_id, str)
                or not gate_id
                or gate_id != gate_id.strip()
                or gate_id in seen
            ):
                expected_valid = False
                continue
            seen.add(gate_id)
            expected_gate_ids.append(gate_id)

    gate_results: dict[str, bool | None] = {}
    gates_valid = isinstance(gates_value, Mapping) and bool(gates_value)
    if isinstance(gates_value, Mapping):
        for gate_id, record in gates_value.items():
            if not isinstance(gate_id, str) or not gate_id:
                gates_valid = False
                continue
            gate_results[gate_id] = _official_gate_result(record)
            if gate_results[gate_id] is None:
                gates_valid = False
    gate_set_complete = (
        expected_valid
        and gates_valid
        and len(gate_results) == len(expected_gate_ids)
        and set(gate_results) == set(expected_gate_ids)
    )

    verifier = evaluation.get("official_verifier")
    verifier_ran = isinstance(verifier, Mapping) and verifier.get("ran") is True
    timed_out = bool(verifier.get("timed_out")) if isinstance(verifier, Mapping) else True
    returncode = verifier.get("returncode") if isinstance(verifier, Mapping) else None
    returncode_valid = isinstance(returncode, int) and not isinstance(returncode, bool)
    evaluation_incomplete = (
        reward is None
        or not gate_set_complete
        or not verifier_ran
        or timed_out
        or not returncode_valid
    )
    passed = sum(result is True for result in gate_results.values())
    gate_score = (
        round(passed / len(expected_gate_ids), 6)
        if gate_set_complete
        else None
    )
    resolved = (
        not evaluation_incomplete
        and math.isclose(reward, 1.0, rel_tol=0, abs_tol=1e-9)
        and all(result is True for result in gate_results.values())
        and returncode == 0
    )
    return {
        "reward": reward,
        "gate_score": gate_score,
        "gate_results": gate_results,
        "evaluation_incomplete": evaluation_incomplete,
        "resolved": resolved,
    }


def _official_gate_result(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, Mapping) or value.get("skipped") is True:
        return None
    passed = value.get("passed")
    if isinstance(passed, bool):
        return passed
    verdict = value.get("verdict")
    if isinstance(verdict, bool):
        return verdict
    if isinstance(verdict, str):
        normalized = verdict.strip().casefold()
        if normalized in {"pass", "passed", "true", "success", "succeeded", "ok", "1"}:
            return True
        if normalized in {"fail", "failed", "false", "error", "0"}:
            return False
    return None
