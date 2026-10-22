"""Crash-recoverable V4 dialogue orchestration and Exposure Ledger commits."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from .actions import AskAction, ClientMessageAction, QuestionAtom, charge_ask
from .canonical import digest_json
from .client import (
    ClientSimulationError,
    SUPERVISION_PROTOCOL_VERSION,
    SupervisedClientSimulator,
    SupervisionAttempt,
)
from .models import BudgetState, OperationError, Registry, StrictModel
from .storage import RevisionConflict, SessionRepository


class DialogueStateError(RuntimeError):
    """Dialogue state cannot safely advance; Candidate-visible text was not emitted."""

    def __init__(self, message: str, *, code: str = "client.render_failed", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable




class PendingExchange(StrictModel):
    operation_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1)
    ledger_event_id: str = Field(min_length=1)
    original_questions: list[str]
    atomic_questions: list[QuestionAtom] | None = None
    charged_count: int = Field(default=0, ge=0)
    charged_round: Literal[0, 1] = 0
    status: Literal["raw", "accepted", "matched", "answering"] = "raw"
    attempt: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    supervision_attempts: list[SupervisionAttempt] = Field(default_factory=list)




class DialogueService:
    """Advance durable question exchanges without duplicate charges or exposure."""

    def __init__(
        self,
        repository: SessionRepository,
        registry: Registry,
        *,
        supervised_client: SupervisedClientSimulator,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry.model_copy(deep=True)
        self._slots_by_id = {slot.slot_id: slot for slot in self._registry.slots}
        self._supervised_client = supervised_client
        self._clock = _utc_now if clock is None else clock
        self._id_factory = _new_id if id_factory is None else id_factory

    def begin_ask(
        self,
        session_id: str,
        action: AskAction | ClientMessageAction,
        *,
        model_trace: dict | None = None,
    ) -> PendingExchange:
        """Persist the Candidate's exact ASK before any fallible infrastructure call."""

        created_at = _timestamp(self._clock())
        identity = {
            "operation_id": self._id_factory("operation"),
            "question_id": self._id_factory("question"),
            "client_message_id": self._id_factory("client_message"),
            "ledger_event_id": self._id_factory("exposure"),
        }

        while True:
            current = self._repository.get_session(session_id)
            dialogue = _dialogue_document(current)
            if dialogue.get("pending_exchange") is not None:
                raise DialogueStateError("a dialogue exchange is already pending")
            if current.get("phase") != "dialogue":
                raise DialogueStateError("session is not accepting dialogue questions")
            original_messages = (
                list(action.questions)
                if isinstance(action, AskAction)
                else [action.message]
            )
            pending = PendingExchange(
                **identity,
                original_questions=original_messages,
                attempt=1,
                created_at=created_at,
            )
            candidate_message = {
                "message_id": pending.question_id,
                "role": "candidate",
                "action": "ask" if isinstance(action, AskAction) else "message",
                "workflow_action": (
                    "ask_client" if isinstance(action, AskAction) else "message_client"
                ),
                "decision_summary": action.decision_summary,
                "content": "\n".join(pending.original_questions),
                "questions": list(pending.original_questions),
                "atomic_questions": [],
                "processing_status": "raw",
                "timestamp": created_at,
            }
            if model_trace is not None:
                candidate_message["model_trace"] = model_trace
            patch = {
                "dialogue": {
                    "messages": [*dialogue.get("messages", []), candidate_message],
                    "pending_exchange": pending.model_dump(mode="json"),
                    "pending_actor": "atomizer",
                    "operation_error": None,
                },
            }
            try:
                self._repository.compare_and_swap(session_id, current["revision"], patch)
                return pending
            except RevisionConflict:
                continue


    def resume_infrastructure(
        self, session_id: str, *, retry: bool = False
    ) -> PendingExchange | None:
        """Annotate and charge a persisted Agent message; never recall Candidate.

        In supervised-Client sessions, the Agent message is already accepted
        dialogue and must not be gated by another model.  A deterministic,
        source-grounded envelope is persisted for disclosure bindings; the
        post-response Supervisor supplies the semantic question and hit counts.
        """

        pending = self._increment_attempt(session_id) if retry else self._current_pending(session_id)
        if pending is None:
            return None
        if pending.atomic_questions is None:
            atoms = _source_grounded_message_atoms(pending.original_questions)
            pending = self._persist_atoms_and_charge(session_id, pending.operation_id, atoms)

        return pending


    def commit_client_response(self, session_id: str) -> dict[str, Any] | None:
        """Render selected records and atomically commit message plus ledger event."""

        pending = self._mark_answering(session_id)
        if pending is None:
            return None
        if pending.atomic_questions is None:
            raise DialogueStateError("question annotation is not yet persisted")
        question = "\n".join(pending.original_questions)
        current = self._repository.get_session(session_id)
        dialogue = _dialogue_document(current)
        current_pending = _pending_exchange(dialogue)
        if current_pending is None or current_pending.operation_id != pending.operation_id:
            raise DialogueStateError("pending exchange changed before client commit")
        previously_revealed = {
            slot_id
            for event in dialogue.get("exposure_ledger", [])
            for slot_id in event.get("revealed_slot_ids", [])
        }
        approved_history = [
            message
            for message in dialogue.get("messages", [])
            if message.get("message_id") != pending.question_id
        ]
        try:
            supervised = self._supervised_client.respond(
                previous_attempts=pending.supervision_attempts,
                on_attempt=lambda attempt: self._persist_supervision_attempt(
                    session_id, pending.operation_id, attempt
                ),
                public_task=str(
                    (current.get("job_context") or {}).get("public_task") or ""
                ),
                candidate_message=question,
                current_client_message_id=pending.client_message_id,
                current_candidate_message_id=pending.question_id,
                approved_history=approved_history,
                previously_disclosed_hidden_ru_ids=sorted(previously_revealed),
                candidate_question_atoms=[
                    atom.model_dump(mode="json")
                    for atom in (pending.atomic_questions or [])
                ],
            )
        except ClientSimulationError as error:
            self._persist_operation_error(
                session_id,
                pending.operation_id,
                OperationError(
                    stage="client_supervision",
                    code=error.code,
                    message=str(error),
                    retryable=error.retryable,
                    operation_id=pending.operation_id,
                ),
                pending_actor="supervisor",
            )
            raise DialogueStateError(
                f"Client supervision failed: {error}", code=error.code, retryable=error.retryable,
            ) from None
        # Each private attempt has a durable checkpoint. Read its latest
        # revision before committing the approved message and ledger once.
        current = self._repository.get_session(session_id)
        dialogue = _dialogue_document(current)
        current_pending = _pending_exchange(dialogue)
        if current_pending is None or current_pending.operation_id != pending.operation_id:
            raise DialogueStateError("pending exchange changed during client supervision")
        disclosed_ids = list(supervised.disclosed_ru_ids)
        hidden_ids = [
            ru_id
            for ru_id in disclosed_ids
            if not self._slots_by_id[ru_id].initially_visible
        ]
        public_ids = [
            ru_id
            for ru_id in disclosed_ids
            if self._slots_by_id[ru_id].initially_visible
        ]
        newly_revealed = list(supervised.newly_disclosed_hidden_ru_ids)
        rendered_text = supervised.text
        payload_hash = digest_json(
            {
                "candidate_message": question,
                "client_message": supervised.text,
            }
        )
        supervision_attempts = [
            {
                **attempt.model_dump(mode="json"),
                "operation_id": pending.operation_id,
                "candidate_message_id": pending.question_id,
                "exchange_attempt": pending.attempt,
            }
            for attempt in supervised.attempts
        ]
        renderer_mode = supervised.mode
        final_supervision = supervision_attempts[-1]
        supervisor_question_count = final_supervision["question_count"]
        supervisor_relevant_question_count = final_supervision["relevant_question_count"]
        triggered_ru_ids = list(final_supervision.get("triggered_ru_ids", []))
        triggered_question_atom_ids = list(
            final_supervision.get("triggered_question_atom_ids", [])
        )
        question_atom_ids_by_ru = dict(
            final_supervision.get("question_atom_ids_by_ru", {})
        )
        annotation_fields = {
            key: final_supervision.get(key)
            for key in ["ru_annotations", "question_counts_by_ru", "followup_question_counts_by_ru", "annotation_status", "annotation_errors"]
        }
        client_message = {
            "message_id": pending.client_message_id,
            "candidate_message_id": pending.question_id,
            "role": "client",
            "content": rendered_text,
            "disclosed_ru_ids": [*public_ids, *hidden_ids],
            "newly_disclosed_hidden_ru_ids": newly_revealed,
            "supervisor_triggered_ru_ids": triggered_ru_ids,
            "supervisor_triggered_question_atom_ids": triggered_question_atom_ids,
            "supervisor_question_count": supervisor_question_count,
            "supervisor_relevant_question_count": supervisor_relevant_question_count,
            **annotation_fields,
            "supervision_protocol_version": SUPERVISION_PROTOCOL_VERSION,
            "supervision_attempts": supervision_attempts,
            "client_mode": renderer_mode,
            "timestamp": _timestamp(self._clock()),
        }
        final_revision = current["revision"] + 1
        ledger_event = {
            "event_id": pending.ledger_event_id,
            "question_id": pending.question_id,
            "question_message_id": pending.question_id,
            "question_atom_ids": [
                atom.atom_id for atom in (pending.atomic_questions or [])
            ],
            "client_message_id": pending.client_message_id,
            "matched_hidden_slot_ids": hidden_ids,
            "already_public_slot_ids": public_ids,
            "revealed_slot_ids": list(newly_revealed),
            "first_exposure_slot_ids": list(newly_revealed),
            "answer_payload_hash": payload_hash,
            "matcher_version": "supervisor.semantic_review.v3",
            **annotation_fields,
            "supervision_attempt_count": len(supervision_attempts),
            "supervision_protocol_version": (
                final_supervision.get("protocol_version")
            ),
            "supervisor_question_count": supervisor_question_count,
            "supervisor_relevant_question_count": supervisor_relevant_question_count,
            "supervisor_triggered_ru_ids": triggered_ru_ids,
            "relevant_question_atom_ids": sorted({
                atom_id
                for ru_id in newly_revealed
                for atom_id in question_atom_ids_by_ru.get(ru_id, [])
            }),
            "question_atom_ids_by_ru": question_atom_ids_by_ru,
            "revision": final_revision,
            "timestamp": pending.created_at,
        }
        patch = {
            "dialogue": {
                "messages": [*dialogue.get("messages", []), client_message],
                "exposure_ledger": [
                    *dialogue.get("exposure_ledger", []),
                    ledger_event,
                ],
                "supervision_events": [
                    *dialogue.get("supervision_events", []),
                    *supervision_attempts,
                ],
                "pending_exchange": None,
                "pending_actor": "candidate",
                "operation_error": None,
            }
        }
        try:
            budget = BudgetState.model_validate(current["budget"])
        except (KeyError, TypeError, ValidationError):
            raise DialogueStateError("session dialogue budget is invalid") from None
        # This legacy execution counter is not a precision denominator. Missing
        # semantic annotations never fabricate zero or change budget accounting.
        if supervisor_question_count is not None:
            placeholder_count = len(pending.atomic_questions or [])
            patch["budget"] = budget.model_copy(update={
                "question_atoms_used": max(0, budget.question_atoms_used
                                           - placeholder_count + supervisor_question_count),
            }).model_dump(mode="json")
        try:
            self._repository.compare_and_swap(session_id, current["revision"], patch)
        except RevisionConflict:
            raise DialogueStateError(
                "client response commit conflicted; exchange remains retryable"
            ) from None
        return client_message

    def _persist_supervision_attempt(
        self, session_id: str, operation_id: str, attempt: SupervisionAttempt
    ) -> None:
        while True:
            current = self._repository.get_session(session_id)
            pending = _pending_exchange(_dialogue_document(current))
            if pending is None or pending.operation_id != operation_id:
                raise DialogueStateError("pending exchange changed during supervision")
            checkpoint = pending.model_copy(update={
                "supervision_attempts": [*pending.supervision_attempts, attempt]
            })
            try:
                self._repository.compare_and_swap(
                    session_id, current["revision"],
                    {"dialogue": {"pending_exchange": checkpoint.model_dump(mode="json")}},
                )
                return
            except RevisionConflict:
                continue

    def _current_pending(self, session_id: str) -> PendingExchange | None:
        current = self._repository.get_session(session_id)
        return _pending_exchange(_dialogue_document(current))

    def _persist_atoms_and_charge(
        self,
        session_id: str,
        operation_id: str,
        atoms: list[QuestionAtom],
    ) -> PendingExchange | None:
        """Persist one successful atomization and charge its budget exactly once."""

        while True:
            current = self._repository.get_session(session_id)
            dialogue = _dialogue_document(current)
            pending = _pending_exchange(dialogue)
            if pending is None or pending.operation_id != operation_id:
                raise DialogueStateError("pending exchange changed during atomization")
            if pending.atomic_questions is not None:
                return pending
            try:
                budget = BudgetState.model_validate(current["budget"])
            except (KeyError, TypeError, ValidationError):
                raise DialogueStateError("session dialogue budget is invalid") from None
            charged = charge_ask(budget, atoms)
            messages = list(dialogue.get("messages", []))
            for index, message in enumerate(messages):
                if message.get("message_id") == pending.question_id:
                    message = dict(message)
                    message["atomic_questions"] = [
                        atom.model_dump(mode="json") for atom in atoms
                    ]
                    message["processing_status"] = (
                        "accepted" if charged.accepted else "rejected"
                    )
                    message["budget_decision"] = {
                        "accepted": charged.accepted,
                        "end_reason": charged.end_reason,
                    }
                    messages[index] = message
                    break
            if not charged.accepted:
                patch = {
                    "dialogue": {
                        "messages": messages,
                        "pending_exchange": None,
                        "pending_actor": "none",
                        "end_reason": charged.end_reason,
                        "operation_error": None,
                    }
                }
                try:
                    self._repository.compare_and_swap(session_id, current["revision"], patch)
                    return None
                except RevisionConflict:
                    continue
            accepted = pending.model_copy(
                update={
                    "atomic_questions": [atom.model_copy(deep=True) for atom in atoms],
                    "charged_count": len(atoms),
                    "charged_round": 1,
                    "status": "accepted",
                }
            )
            patch = {
                "budget": charged.budget.model_dump(mode="json"),
                "dialogue": {
                    "messages": messages,
                    "pending_exchange": accepted.model_dump(mode="json"),
                    "pending_actor": "client_simulator",
                    "end_reason": charged.end_reason,
                    "operation_error": None,
                },
            }
            try:
                self._repository.compare_and_swap(session_id, current["revision"], patch)
                return accepted
            except RevisionConflict:
                continue

    def _increment_attempt(self, session_id: str) -> PendingExchange | None:
        while True:
            current = self._repository.get_session(session_id)
            dialogue = _dialogue_document(current)
            pending = _pending_exchange(dialogue)
            if pending is None:
                return None
            incremented = pending.model_copy(update={"attempt": pending.attempt + 1})
            try:
                self._repository.compare_and_swap(
                    session_id,
                    current["revision"],
                    {"dialogue": {"pending_exchange": incremented.model_dump(mode="json")}},
                )
                return incremented
            except RevisionConflict:
                continue


    def _mark_answering(self, session_id: str) -> PendingExchange | None:
        while True:
            current = self._repository.get_session(session_id)
            dialogue = _dialogue_document(current)
            pending = _pending_exchange(dialogue)
            if pending is None:
                return None
            if pending.atomic_questions is None:
                return pending
            if pending.status == "answering":
                return pending
            answering = pending.model_copy(update={"status": "answering"})
            try:
                self._repository.compare_and_swap(
                    session_id,
                    current["revision"],
                    {
                        "dialogue": {
                            "pending_exchange": answering.model_dump(mode="json"),
                            "pending_actor": "client_simulator",
                        }
                    },
                )
                return answering
            except RevisionConflict:
                continue

    def _persist_operation_error(
        self,
        session_id: str,
        operation_id: str,
        error: OperationError,
        *,
        pending_actor: str,
        supervision_events: list[dict[str, Any]] | None = None,
    ) -> None:
        error_document = error.model_dump(mode="json")
        while True:
            current = self._repository.get_session(session_id)
            dialogue = _dialogue_document(current)
            pending = _pending_exchange(dialogue)
            if pending is None or pending.operation_id != operation_id:
                raise DialogueStateError("pending exchange changed while recording an error")
            errors = list(current.get("errors", []))
            if not errors or errors[-1] != error_document:
                errors.append(error_document)
            patch = {
                "errors": errors,
                "dialogue": {
                    "operation_error": error_document,
                    "pending_actor": pending_actor,
                    **(
                        {
                            "supervision_events": [
                                *dialogue.get("supervision_events", []),
                                *(supervision_events or []),
                            ]
                        }
                        if supervision_events
                        else {}
                    ),
                },
            }
            try:
                self._repository.compare_and_swap(session_id, current["revision"], patch)
                return
            except RevisionConflict:
                continue




def _dialogue_document(session: dict[str, Any]) -> dict[str, Any]:
    dialogue = session.get("dialogue")
    if not isinstance(dialogue, dict):
        raise DialogueStateError("session dialogue state is invalid")
    return dialogue


def _pending_exchange(dialogue: dict[str, Any]) -> PendingExchange | None:
    raw = dialogue.get("pending_exchange")
    if raw is None:
        return None
    try:
        return PendingExchange.model_validate(raw)
    except (TypeError, ValidationError):
        raise DialogueStateError("pending dialogue exchange is invalid") from None


_LIST_ITEM_START = re.compile(r"(?m)^[ \t]*(?:[-*+]\s+|\d{1,3}[.)]\s+)")
_INFORMATION_REQUEST_CUE = re.compile(
    r"(?i)\b(?:"
    r"confirm|clarif\w*|specif\w*|explain|tell|provide|share|"
    r"let\s+me\s+know|prefer|acceptable|okay|correct|agree|"
    r"what|which|when|where|why|how|whether|should|could|would|"
    r"do\s+you|is\s+it|are\s+there|want\s+to\s+match"
    r")\b"
)


def _trimmed_span(source: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _countable_question_spans(source: str) -> list[tuple[int, int]]:
    """Find source-grounded question segments without gating Agent prose.

    This is deliberately a permissive, post-acceptance segmentation aid for the
    Supervisor.  It never rejects or rewrites a message.  Explicit question
    marks are separate countable requests, while numbered/bulleted requests
    without punctuation remain independently countable when they contain an
    information-seeking cue.
    """

    item_starts = [match.start() for match in _LIST_ITEM_START.finditer(source)]
    ranges: list[tuple[int, int]] = []
    if item_starts:
        preamble = (0, item_starts[0])
        if "?" in source[preamble[0] : preamble[1]]:
            ranges.append(preamble)
        ranges.extend(
            (start, item_starts[index + 1] if index + 1 < len(item_starts) else len(source))
            for index, start in enumerate(item_starts)
        )
    else:
        ranges.append((0, len(source)))

    spans: list[tuple[int, int]] = []
    for range_start, range_end in ranges:
        cursor = range_start
        for question_mark in re.finditer(r"\?", source[range_start:range_end]):
            end = range_start + question_mark.end()
            span = _trimmed_span(source, cursor, end)
            if span is not None:
                spans.append(span)
            cursor = end
        tail = _trimmed_span(source, cursor, range_end)
        if tail is not None and _INFORMATION_REQUEST_CUE.search(
            source[tail[0] : tail[1]]
        ):
            spans.append(tail)
    return spans


def _source_grounded_message_atoms(messages: list[str]) -> list[QuestionAtom]:
    """Create non-blocking source bindings for already accepted Agent messages.

    Countable spans help the post-response Supervisor distinguish several
    questions asked in one natural message.  If no request can be segmented, a
    non-matchable blanket envelope preserves provenance without counting an
    acknowledgement or background statement as a question.
    """

    atoms: list[QuestionAtom] = []
    for source_index, source in enumerate(messages):
        if not isinstance(source, str):
            continue
        whole = _trimmed_span(source, 0, len(source))
        if whole is None:
            continue
        spans = _countable_question_spans(source)
        if not spans:
            start, end = whole
            atoms.append(
                QuestionAtom(
                    atom_id=f"q{source_index}.a0",
                    text=source[start:end],
                    source_question_index=source_index,
                    source_span={"start": start, "end": end},
                    blanket=True,
                    matchable=False,
                )
            )
            continue
        for atom_index, (start, end) in enumerate(spans):
            atoms.append(
                QuestionAtom(
                    atom_id=f"q{source_index}.a{atom_index}",
                    text=source[start:end],
                    source_question_index=source_index,
                    source_span={"start": start, "end": end},
                )
            )
    return atoms


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("dialogue clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(kind: str) -> str:
    return f"{kind}-{uuid4().hex}"
