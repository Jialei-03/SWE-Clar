"""Strict candidate actions, question atomization, and budget charging for V4."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import Field, StrictInt, ValidationError, field_validator, model_validator

from .models import BudgetState, StrictModel


class CandidateActionError(ValueError):
    """A stable, client-safe failure to produce a structured candidate action."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code




class AskAction(StrictModel):
    action: Literal["ask"]
    questions: list[str]
    decision_summary: str | None = Field(default=None, min_length=1, max_length=500)


class ClientMessageAction(StrictModel):
    action: Literal["message"]
    message: str = Field(min_length=1)
    decision_summary: str | None = Field(default=None, min_length=1, max_length=500)


class ReadyAction(StrictModel):
    action: Literal["ready"]
    decision_summary: str | None = Field(default=None, min_length=1, max_length=500)


class QuestionAtom(StrictModel):
    atom_id: str
    text: str = Field(min_length=1)
    source_question_index: int = Field(ge=0)
    source_span: dict[str, StrictInt]
    blanket: bool = False
    matchable: bool = True

    @field_validator("source_span")
    @classmethod
    def source_span_is_a_closed_range(
        cls, value: dict[str, StrictInt]
    ) -> dict[str, StrictInt]:
        if set(value) != {"start", "end"}:
            raise ValueError("source_span requires start and end")
        start, end = value["start"], value["end"]
        if start < 0 or end <= start:
            raise ValueError("source_span must be an ordered non-negative range")
        return value

    @model_validator(mode="after")
    def blanket_atoms_are_non_matchable(self) -> "QuestionAtom":
        if self.blanket and self.matchable:
            raise ValueError("blanket atoms are non-matchable")
        if not self.blanket and not self.matchable:
            raise ValueError("only blanket atoms may be non-matchable")
        return self


class AcceptedAsk(StrictModel):
    accepted: bool
    atoms: list[QuestionAtom]
    budget: BudgetState
    end_reason: str | None = None












def parse_candidate_action(text: str) -> AskAction | ClientMessageAction | ReadyAction:
    """Parse exactly one candidate action and hide schema implementation details."""

    try:
        document = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise CandidateActionError("action.invalid_json", "candidate action must be valid JSON") from None
    if not isinstance(document, dict):
        raise CandidateActionError("action.invalid_schema", "candidate action must be an object")

    try:
        if document.get("action") == "ask":
            return AskAction.model_validate(document)
        if document.get("action") == "message":
            return ClientMessageAction.model_validate(document)
        if document.get("action") == "ready":
            return ReadyAction.model_validate(document)
    except ValidationError:
        pass
    raise CandidateActionError("action.invalid_schema", "candidate action has an invalid schema")




def charge_ask(budget: BudgetState, atoms: list[QuestionAtom]) -> AcceptedAsk:
    """Record one dialogue turn and its question atoms.

    New Clarify sessions have nullable limits, so this function only updates
    telemetry and never ends the dialogue.  Explicit numeric limits are kept
    solely for reading and replaying historical finite-budget sessions.
    """

    if budget.question_atom_limit == 0:
        return _rejected(budget, atoms, "zero_question_budget")
    if (
        budget.dialogue_round_limit is not None
        and budget.dialogue_rounds_used >= budget.dialogue_round_limit
    ):
        return _rejected(budget, atoms, "round_budget_exhausted")
    if (
        budget.question_atom_limit is not None
        and budget.question_atoms_used >= budget.question_atom_limit
    ):
        return _rejected(budget, atoms, "question_budget_exhausted")
    if (
        budget.question_atom_limit is not None
        and len(atoms) > budget.question_atom_limit - budget.question_atoms_used
    ):
        return _rejected(budget, atoms, "question_budget_exhausted")

    charged = BudgetState(
        question_atom_limit=budget.question_atom_limit,
        dialogue_round_limit=budget.dialogue_round_limit,
        question_atoms_used=budget.question_atoms_used + len(atoms),
        dialogue_rounds_used=budget.dialogue_rounds_used + 1,
    )
    if (
        charged.dialogue_round_limit is not None
        and charged.dialogue_rounds_used == charged.dialogue_round_limit
    ):
        end_reason = "round_budget_exhausted"
    elif (
        charged.question_atom_limit is not None
        and charged.question_atoms_used == charged.question_atom_limit
    ):
        end_reason = "question_budget_exhausted"
    else:
        end_reason = None
    return AcceptedAsk(accepted=True, atoms=atoms, budget=charged, end_reason=end_reason)


def _rejected(budget: BudgetState, atoms: list[QuestionAtom], end_reason: str) -> AcceptedAsk:
    return AcceptedAsk(accepted=False, atoms=atoms, budget=budget, end_reason=end_reason)












_INFORMATION_REQUEST = re.compile(
    r"^\s*(?:"
    r"(?:who|what|when|where|why|how|which)\b"
    r"|(?:is|are|am|was|were|do|does|did|can|could|would|should|will|may|must|has|have|had)\b"
    r"|(?:please\s+)?(?:tell|give|show|list|provide|explain|describe|clarify|confirm|specify|identify|state|share)\b"
    r"|let\s+me\s+know\b"
    r"|i\s+(?:need|want|would\s+like)\s+to\s+know\b"
    r")",
    re.IGNORECASE,
)

def _is_information_request(text: str) -> bool:
    """Keep actual questions and explicit information requests; drop narration."""

    normalized = text.strip()
    return bool("?" in normalized or _INFORMATION_REQUEST.search(normalized))
