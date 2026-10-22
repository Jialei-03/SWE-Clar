"""Audit answers, fixed semantic judging, and clarification metrics."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import AliasChoices, Field, model_validator

from .models import RequirementRecord, RequirementUnit, Registry, StrictModel


AUDIT_SCORER_VERSION = "swe-clar.audit.lexical_content.v1"
SEMANTIC_AUDIT_SCORER_VERSION = "swe-clar.audit.semantic_content.swe-clar"
SEMANTIC_AUDIT_PROMPT_VERSION = "swe-clar.audit.content.swe-clar"


SEMANTIC_AUDIT_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ru_id", "content_correct", "reason"],
                "properties": {
                    "ru_id": {"type": "string", "minLength": 1},
                    "content_correct": {"type": "boolean"},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}


class AuditSchemaError(ValueError):
    pass


class AuditAnswer(StrictModel):
    ru_id: str = Field(min_length=1, validation_alias=AliasChoices("ru_id", "slot_id"))

    @property
    def slot_id(self) -> str:
        return self.ru_id
    status: Literal["known", "unknown"]
    value: Any | None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def read_historical_answer(cls, value):
        if isinstance(value, dict) and "source_refs" in value:
            value = {key: item for key, item in value.items() if key != "source_refs"}
        return value

    @model_validator(mode="after")
    def known_and_unknown_shapes(self) -> "AuditAnswer":
        if self.status == "unknown" and self.value is not None:
            raise ValueError("unknown answers require null value")
        if self.status == "known" and self.value is None:
            raise ValueError("known answers require a value")
        return self


class AuditOutput(StrictModel):
    answers: list[AuditAnswer]


class SemanticAuditVerdict(StrictModel):
    ru_id: str = Field(min_length=1, validation_alias=AliasChoices("ru_id", "slot_id"))

    @property
    def slot_id(self) -> str:
        return self.ru_id
    content_correct: bool
    reason: str = Field(min_length=1)
    tier_label: Literal['correct', 'partial', 'omitted', 'contradiction'] | None = None
    evidence: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode='after')
    def consistent_tier(self):
        if self.tier_label is not None and self.content_correct != (self.tier_label == 'correct'):
            raise ValueError('tier and strict correctness disagree')
        return self


class SemanticAuditJudgment(StrictModel):
    verdicts: list[SemanticAuditVerdict]

    @model_validator(mode='after')
    def homogeneous_protocol(self):
        if len({v.tier_label is None for v in self.verdicts}) > 1:
            raise ValueError('Cannot mix legacy and tiered verdicts')
        return self


class ClarificationMetrics(StrictModel):
    scorer_version: str
    scoring_basis: Literal[
        "lexical_content_only",
        "semantic_content_only",
    ] = "lexical_content_only"
    requirement_understanding_accuracy: float
    content_semantic_accuracy: float | None = None
    judge_model: str | None = None
    judge_prompt_version: str | None = None
    value_accuracy: float
    answer_coverage: float
    hallucination_rate: float
    per_slot: dict[str, dict[str, Any]]
    tiered_understanding_accuracy: float | None = None
    strict_ru_understanding_accuracy: float | None = None
    contradiction_rate: float | None = None


def validate_audit_output(raw: object, registry: Registry) -> AuditOutput:
    try:
        output = AuditOutput.model_validate(raw)
    except Exception:
        raise AuditSchemaError("audit output does not match the required schema") from None
    expected = [slot.slot_id for slot in registry.slots]
    actual = [answer.slot_id for answer in output.answers]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise AuditSchemaError("audit output must answer every RU exactly once")
    by_id = {answer.slot_id: answer for answer in output.answers}
    return AuditOutput(answers=[by_id[slot_id] for slot_id in expected])


def build_semantic_judge_payload(
    output: AuditOutput,
    registry: Registry,
    *,
    frozen_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only gold-bearing payload visible to the fixed Audit judge.

    Source references are intentionally excluded: the primary metric judges
    whether the Coding Agent understood the requirement's meaning, not whether
    it formatted a provenance citation correctly.
    """

    return {
        "prompt_version": SEMANTIC_AUDIT_PROMPT_VERSION,
        "items": [
            {
                "ru_id": slot.slot_id,
                "audit_question": slot.audit_question,
                "reference_answer": _reference_answer(slot),
                "candidate_status": answer.status,
                "candidate_answer": answer.value,
            }
            for slot, answer in zip(registry.slots, output.answers, strict=True)
        ],
        "response_schema": SEMANTIC_AUDIT_RESPONSE_SCHEMA,
    }


def build_audit_trace_items(
    output: AuditOutput,
    registry: Registry,
    judgment: SemanticAuditJudgment | None = None,
) -> list[dict[str, Any]]:
    """Join the complete researcher-facing Audit record per Requirement Unit.

    This document is deliberately stored only on the Audit branch.  Coding is
    constructed from the earlier frozen evidence and never receives these
    questions, reference answers, candidate answers, or judge verdicts.
    """

    verdicts = (
        {verdict.slot_id: verdict for verdict in judgment.verdicts}
        if judgment is not None
        else {}
    )
    items: list[dict[str, Any]] = []
    for slot, answer in zip(registry.slots, output.answers, strict=True):
        verdict = verdicts.get(slot.slot_id)
        items.append(
            {
                "requirement_unit_id": slot.slot_id,
                "audit_question": slot.audit_question,
                "reference_answer": _reference_answer(slot),
                "coding_agent_answer": answer.value,
                "coding_agent_status": answer.status,
                "confidence": answer.confidence,
                "content_correct": (
                    verdict.content_correct if verdict is not None else None
                ),
                "judge_reason": verdict.reason if verdict is not None else None,
                "tier_label": verdict.tier_label if verdict is not None else None,
                "judge_evidence": verdict.evidence if verdict is not None else [],
            }
        )
    return items


def validate_semantic_audit_judgment(
    raw: object,
    registry: Registry,
) -> SemanticAuditJudgment:
    try:
        judgment = SemanticAuditJudgment.model_validate(raw)
    except Exception:
        raise AuditSchemaError(
            "semantic Audit judgment does not match the required schema"
        ) from None
    expected = [slot.slot_id for slot in registry.slots]
    actual = [verdict.slot_id for verdict in judgment.verdicts]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise AuditSchemaError(
            "semantic Audit judgment must score every Registry unit exactly once"
        )
    by_id = {verdict.slot_id: verdict for verdict in judgment.verdicts}
    return SemanticAuditJudgment(
        verdicts=[by_id[slot_id] for slot_id in expected]
    )


def score_clarification(
    output: AuditOutput,
    registry: Registry,
    exposure_ledger: list[dict[str, Any]],
    *,
    question_atoms_used: int,
    benchmark_mode: str = "clarify",
    semantic_judgment: SemanticAuditJudgment | None = None,
    judge_model: str | None = None,
) -> ClarificationMetrics:
    revealed_hidden: set[str] = set()
    for event in exposure_ledger:
        slots = set(event.get("revealed_slot_ids", []))
        if event.get("origin") != "oracle":
            revealed_hidden.update(slots)

    total_rus = len(registry.slots)
    semantic_by_id = (
        {verdict.slot_id: verdict for verdict in semantic_judgment.verdicts}
        if semantic_judgment is not None
        else {}
    )
    value_points = understanding_points = 0.0
    tiered = bool(semantic_by_id) and all(v.tier_label is not None for v in semantic_by_id.values())
    contradiction_count = 0
    known_count = wrong_known = 0
    recovered_revealed = 0
    per_slot: dict[str, dict[str, Any]] = {}

    for slot, answer in zip(registry.slots, output.answers, strict=True):
        verdict = semantic_by_id.get(slot.slot_id)
        value_ok = answer.status == "known" and (
            verdict.content_correct
            if verdict is not None
            else _value_matches(answer.value, slot)
        )
        understanding_ok = value_ok
        understanding_score = (
            {'correct': 1.0, 'partial': 0.5, 'omitted': 0.0, 'contradiction': 0.0}[verdict.tier_label]
            if tiered and answer.status == 'known' else float(value_ok)
        )
        contradiction_count += int(tiered and verdict.tier_label == 'contradiction')
        if answer.status == "known":
            known_count += 1
            wrong_known += int(verdict.tier_label == 'contradiction' if tiered else not value_ok)
        value_points += int(value_ok)
        understanding_points += understanding_score
        if slot.slot_id in revealed_hidden and understanding_ok:
            recovered_revealed += 1
        per_slot[slot.slot_id] = {
            "value_correct": value_ok,
            "content_correct": value_ok,
            "scored_correct": understanding_ok,
            "judgment_reason": verdict.reason if verdict is not None else None,
            "status": answer.status,
            "tier_label": verdict.tier_label if tiered else None,
            "understanding_score": understanding_score,
        }

    hidden = {slot.slot_id for slot in registry.slots if not slot.initially_visible}
    clarification_metrics_apply = benchmark_mode == "clarify"
    exposed_count = len(hidden & revealed_hidden) if clarification_metrics_apply else 0
    understanding_accuracy = (
        understanding_points / total_rus if total_rus else 0.0
    )
    return ClarificationMetrics(
        scorer_version=(
            'swe-clar.audit.ru_tiered.v1' if tiered else SEMANTIC_AUDIT_SCORER_VERSION
            if semantic_judgment is not None
            else AUDIT_SCORER_VERSION
        ),
        scoring_basis=(
            "semantic_content_only"
            if semantic_judgment is not None
            else "lexical_content_only"
        ),
        requirement_understanding_accuracy=round(understanding_accuracy, 6),
        tiered_understanding_accuracy=round(understanding_accuracy, 6) if tiered else None,
        strict_ru_understanding_accuracy=round(value_points / total_rus, 6) if tiered and total_rus else None,
        contradiction_rate=round(contradiction_count / total_rus, 6) if tiered and total_rus else None,
        content_semantic_accuracy=(
            round(value_points / total_rus, 6)
            if semantic_judgment is not None and total_rus
            else 0.0
            if semantic_judgment is not None
            else None
        ),
        judge_model=judge_model if semantic_judgment is not None else None,
        judge_prompt_version=(
            'swe-clar.audit.ru_tiered.v1' if tiered else SEMANTIC_AUDIT_PROMPT_VERSION
            if semantic_judgment is not None
            else None
        ),
        value_accuracy=round(value_points / total_rus, 6) if total_rus else 0.0,
        answer_coverage=round(known_count / len(registry.slots), 6) if registry.slots else 0.0,
        hallucination_rate=round(wrong_known / known_count, 6) if known_count else 0.0,
        per_slot=per_slot,
    )


def _reference_answer(slot: RequirementRecord) -> Any:
    if isinstance(slot, RequirementUnit):
        return {'required_behavior':slot.content,
                'agreed_delivery_interface':slot.test_interface.model_dump(mode='json') if slot.test_interface else None}
    return {
        "canonical": slot.value.canonical,
        "accepted_aliases": slot.value.accepted_aliases,
        "prepared_answer": slot.prepared_answer,
        "required_facts": slot.value.required_facts,
    }


def _value_matches(candidate: Any, slot: RequirementRecord) -> bool:
    if isinstance(slot, RequirementUnit):
        if not isinstance(candidate, str):
            return False
        expected = _norm(slot.content)
        actual = _norm(candidate)
        return actual == expected or (bool(expected) and expected in actual)
    value = slot.value
    if value.type == "enum":
        if not isinstance(candidate, str):
            return False
        # ``canonical`` enum labels are internal annotation IDs and are never
        # exposed to the Audit Agent.  ``prepared_answer`` is the Registry's
        # adjudicated natural-language rendering and is emitted verbatim by the
        # Client simulator, so accepting it exactly keeps scoring extractive and
        # deterministic without leaking the label.
        accepted = [value.canonical, *value.accepted_aliases, slot.prepared_answer]
        if _norm(candidate) in {_norm(item) for item in accepted}:
            return True
        # Some concise, semantically correct Audit answers omit framing words
        # from the evidence sentence.  Tasks may opt in to a pre-registered
        # lexical rubric; there is deliberately no global fuzzy or LLM judge.
        return _semantic_rubric_matches(
            candidate, value.comparator.get("semantic_match")
        )
    if value.type == "set":
        if not isinstance(candidate, (list, tuple, set)):
            return False
        expected = {_norm(item) for item in value.canonical}
        actual = {_norm(item) for item in candidate}
        allow_extra = bool(value.comparator.get("allow_extra_elements"))
        return expected <= actual if allow_extra else expected == actual
    if value.type == "boolean":
        return type(candidate) is bool and candidate is value.canonical
    if value.type == "number":
        return isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate == value.canonical
    if value.type == "string":
        return isinstance(candidate, str) and _norm(candidate) == _norm(value.canonical)
    if value.type == "structured":
        return candidate == value.canonical
    if value.type == "free_text":
        if not isinstance(candidate, str):
            return False
        text = _norm(candidate)
        accepted_renderings = [
            value.canonical,
            *value.accepted_aliases,
            slot.prepared_answer,
        ]
        # The Audit Agent is asked to copy grounded evidence.  A copied Client
        # answer may be longer than the annotation's canonical value, so an
        # exact registered rendering embedded in that answer is deterministic
        # evidence of correctness rather than a fuzzy semantic match.
        if any(
            normalized and normalized in text
            for normalized in (_norm(item) for item in accepted_renderings)
        ):
            return True
        # Required facts are annotation-time concepts, not literal phrases.
        # Match their normalized tokens in order while allowing harmless
        # modifiers (for example "visible thin borders" for "visible
        # borders") and simple inflection ("separately" / "separate").
        return all(_ordered_fact_matches(candidate, fact) for fact in value.required_facts)
    return False


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _lexical_stem(token: str) -> str:
    for suffix in ("ingly", "edly", "ly", "ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _ordered_fact_matches(candidate: str, fact: Any) -> bool:
    expected = [part for part in _norm(fact).split("_") if part]
    actual = [part for part in _norm(candidate).split("_") if part]
    if not expected or not actual:
        return False
    cursor = 0
    for wanted in expected:
        wanted_stem = _lexical_stem(wanted)
        for index in range(cursor, len(actual)):
            if _lexical_stem(actual[index]) == wanted_stem:
                cursor = index + 1
                break
        else:
            return False
    return True


def _semantic_rubric_matches(candidate: str, rubric: Any) -> bool:
    """Apply an annotation-time, conjunctive lexical rubric.

    ``all_of`` is a list of concept groups.  At least one whole normalized
    phrase from every group must occur in the answer.  ``none_of`` phrases
    reject explicit contradictory formulations.  Registry validation guarantees
    the persisted shape; defensive checks here make direct programmatic use fail
    closed.
    """

    if not isinstance(rubric, dict):
        return False
    groups = rubric.get("all_of")
    forbidden = rubric.get("none_of", [])
    if (
        not isinstance(groups, list)
        or not groups
        or not isinstance(forbidden, list)
    ):
        return False
    text = f"_{_norm(candidate)}_"

    def contains(phrase: Any) -> bool:
        normalized = _norm(phrase) if isinstance(phrase, str) else ""
        return bool(normalized) and f"_{normalized}_" in text

    if any(contains(phrase) for phrase in forbidden):
        return False
    return all(
        isinstance(group, list)
        and bool(group)
        and any(contains(phrase) for phrase in group)
        for group in groups
    )
