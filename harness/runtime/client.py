"""Controlled and supervised Client simulation for SWE-Clar dialogue."""

from __future__ import annotations

import re
import json
from copy import deepcopy
from typing import Any, Callable, Protocol

from pydantic import Field, StrictInt, StrictStr, model_validator

from llm import LLMError

from .models import Registry, RequirementRecord, StrictModel
from .online_annotations import RUAnnotation


EMPTY_MATCH_TEXT = "The available project record has no additional answer for that question."
SUPERVISION_PROTOCOL_VERSION = "contract_grounded_review.v4.decision_level"
MAX_CLIENT_DRAFTS = 6




class ClientDraftTransport(Protocol):
    """Generate one natural-language Client reply draft."""

    def draft(self, payload: dict[str, Any]) -> object: ...


class DisclosureSupervisorTransport(Protocol):
    """Review a Client draft before it becomes candidate-visible."""

    def review(self, payload: dict[str, Any]) -> object: ...


class ClientSimulationError(RuntimeError):
    """The supervised Client loop could not produce an authorized reply."""

    def __init__(
        self,
        message: str,
        *,
        attempts: list["SupervisionAttempt"] | None = None,
        code: str = "client.supervision_failed",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.attempts = list(attempts or [])
        self.code = code
        self.retryable = retryable


class ClientDraft(StrictModel):
    message: StrictStr = Field(min_length=1)
    interface_names: list[StrictStr] = Field(default_factory=list)
    contract_conflict: StrictStr | None = None


class SupervisorReview(StrictModel):
    ru_annotations: list[RUAnnotation] | None = None
    decision: str
    disclosed_ru_ids: list[str] = Field(default_factory=list)
    newly_disclosed_hidden_ru_ids: list[str] = Field(default_factory=list)
    triggered_ru_ids: list[str] = Field(default_factory=list)
    triggered_question_atom_ids: list[str] = Field(default_factory=list)
    question_atom_ids_by_ru: dict[str, list[str]] = Field(default_factory=dict)
    question_count: StrictInt | None = Field(default=None, ge=0)
    relevant_question_count: StrictInt | None = Field(default=None, ge=0)
    question_counts_by_ru: dict[str, StrictInt] | None = None
    followup_question_counts_by_ru: dict[str, StrictInt] | None = None
    annotation_status: str = "unavailable"
    annotation_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def optional_annotations(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = deepcopy(value)
        errors=list(value.get('annotation_errors') or [])
        rows=value.get('ru_annotations')
        if rows is not None:
            try:
                if not isinstance(rows,list):raise ValueError('Expected RU annotation list')
                value['ru_annotations']=[RUAnnotation.model_validate(r) for r in rows]
            except Exception:
                value['ru_annotations']=None
                errors.append('RU annotations unavailable; reply decision is independent')
        value['annotation_status']='valid' if value.get('ru_annotations') is not None else 'unavailable'
        value['annotation_errors']=errors

        return value

    violations: list[str] = Field(default_factory=list)
    rewrite_instruction: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def decision_contract_is_consistent(self) -> "SupervisorReview":
        if not self.reason.strip():
            raise ValueError("Supervisor requires a nonempty decision reason")
        if self.decision not in {"approve", "revise"}:
            raise ValueError("Supervisor decision must be approve or revise")
        if self.decision == "approve":
            if self.violations:
                raise ValueError("approved Client drafts cannot retain violations")
            if self.rewrite_instruction is not None:
                raise ValueError(
                    "approved Client drafts cannot include a rewrite instruction"
                )
        elif not (self.rewrite_instruction or "").strip():
            raise ValueError("rejected Client drafts require a rewrite instruction")
        return self




class SupervisionAttempt(StrictModel):
    ru_annotations: list[RUAnnotation] | None = None
    attempt: int = Field(ge=1)
    client_draft: str
    decision: str
    disclosed_ru_ids: list[str]
    newly_disclosed_hidden_ru_ids: list[str]
    triggered_ru_ids: list[str]
    violations: list[str]
    rewrite_instruction: str | None
    reason: str
    authorized_ru_ids: list[str] = Field(default_factory=list)
    trigger_reason: str | None = None
    question_count: StrictInt | None = Field(default=None, ge=0)
    relevant_question_count: StrictInt | None = Field(default=None, ge=0)
    question_counts_by_ru: dict[str, StrictInt] | None = None
    followup_question_counts_by_ru: dict[str, StrictInt] | None = None
    annotation_status: str = "unavailable"
    annotation_errors: list[str] = Field(default_factory=list)
    triggered_question_atom_ids: list[str] = Field(default_factory=list)
    question_atom_ids_by_ru: dict[str, list[str]] = Field(default_factory=dict)
    trigger_trace: dict[str, Any] | None = None
    client_trace: dict[str, Any] | None = None
    supervisor_trace: dict[str, Any] | None = None
    # Read historical bounded_grounded.v1 checkpoints without rewriting them.
    corrections: list[dict[str, Any]] = Field(default_factory=list)
    protocol_version: str | None = None


class SupervisedClientRender(StrictModel):
    text: str = Field(min_length=1)
    disclosed_ru_ids: list[str]
    newly_disclosed_hidden_ru_ids: list[str]
    attempts: list[SupervisionAttempt] = Field(min_length=1)
    mode: str = "supervised_client.v5"


class SupervisedClientSimulator:
    """Blocking generator–critic loop for natural Client conversation.

    The Client and Supervisor receive normalized Requirement Unit content and
    the same canonical public delivery agreement and a read-only catalog of
    task-local acceptance sources. These private sources, audit prompts and
    rejected drafts are never candidate input.
    """

    def __init__(
        self,
        registry: Registry,
        draft_transport: ClientDraftTransport,
        supervisor_transport: DisclosureSupervisorTransport,
        *,
        project_context: dict[str, Any] | None = None,
    ) -> None:
        self._registry = registry.model_copy(deep=True)
        self._draft_transport = draft_transport
        self._supervisor_transport = supervisor_transport
        self._units_by_id = {unit.slot_id: unit for unit in self._registry.slots}
        self._wire_units = [self._wire_unit(unit) for unit in self._registry.slots]
        self._project_context = deepcopy(project_context or {})
        if self._project_context.get('context_protocol')=='role-context.v2':
            references={r['name']:r['path'] for r in self._project_context['requirement_catalog']}
            self._wire_units=[{'ru_id':u['ru_id'],'name':u['name'],
                              'benchmark_visibility':u['benchmark_visibility'],
                              'requirement_reference':references[u['name']]} for u in self._wire_units]

    def respond(
        self,
        *,
        public_task: str,
        candidate_message: str,
        approved_history: list[dict[str, Any]],
        previously_disclosed_hidden_ru_ids: list[str],
        current_client_message_id: str = "current-client",
        current_candidate_message_id: str = "current-candidate",
        candidate_question_atoms: list[dict[str, Any]] | None = None,
        previous_attempts: list[SupervisionAttempt] | None = None,
        on_attempt: Callable[[SupervisionAttempt], None] | None = None,
    ) -> SupervisedClientRender:
        candidate_message = candidate_message.strip()
        if not candidate_message:
            raise ClientSimulationError("candidate message must not be empty")
        previous_hidden = {ru for ru in previously_disclosed_hidden_ru_ids
                           if isinstance(ru, str) and ru in self._units_by_id}
        history = [
            {
                key: deepcopy(message[key])
                for key in ("role", "content")
                if key in message
            }
            for message in approved_history
            if isinstance(message, dict)
            and message.get("role") in {"candidate", "client"}
        ]
        attempts = list(previous_attempts or [])
        if any(a.protocol_version != SUPERVISION_PROTOCOL_VERSION for a in attempts):
            raise ClientSimulationError(
                "Historical supervision checkpoints are read-only under this protocol; start a new exchange",
                attempts=attempts, code="client.supervision_protocol_mismatch", retryable=False,
            )

        def record_attempt(attempt: SupervisionAttempt) -> None:
            attempt.protocol_version = SUPERVISION_PROTOCOL_VERSION
            attempts.append(attempt)
            if on_attempt is not None:
                on_attempt(attempt)

        if attempts and attempts[-1].decision == "approve":
            approved = attempts[-1]
            return SupervisedClientRender(
                text=approved.client_draft,
                disclosed_ru_ids=approved.disclosed_ru_ids,
                newly_disclosed_hidden_ru_ids=approved.newly_disclosed_hidden_ru_ids,
                attempts=attempts,
            )
        client_public_task = self._client_public_task(public_task)
        role_public_task=self._project_context.get('job_description',public_task)
        if self._project_context.get('context_protocol')=='role-context.v2':
            client_public_task=role_public_task
        question_atoms = deepcopy(candidate_question_atoms or [])
        attempt_number = len(attempts)

        def stop(message: str, code: str) -> None:
            raise ClientSimulationError(message, attempts=attempts, code=code, retryable=False)

        if attempts and attempts[-1].decision == "invalid_supervisor_output":
            stop("Supervisor output exhausted; the frozen draft requires review",
                 "client.supervisor_exhausted")

        while True:
            # The budget belongs to the durable exchange, not a process or model.
            # Recovery must not provide a fresh lottery of judge approvals.
            if sum(a.decision in {"revise", "invalid_client_output"} for a in attempts) >= MAX_CLIENT_DRAFTS:
                stop("Client supervision exhausted; no reply was released",
                     "client.supervision_exhausted")
            attempt_number += 1
            # The Client needs the behavior and delivery interface, not the
            # benchmark's internal identifiers or visibility labels. Keeping
            # IDs researcher-side prevents an otherwise grounded model from
            # echoing ``RU-004`` into candidate-visible conversation.
            client_units = [
                {
                    key: deepcopy(value)
                    for key, value in unit.items()
                    if key not in {"ru_id", "benchmark_visibility"}
                }
                for unit in self._wire_units
            ]
            draft_payload = {
                "schema_version": 1,
                "public_task": client_public_task,
                "conversation": history,
                "candidate_message": candidate_message,
                "requirement_units": client_units,
                "project_context": deepcopy(self._project_context),
                "previous_draft": attempts[-1].client_draft if attempts else None,
                "revision_instruction": attempts[-1].rewrite_instruction if attempts else None,
            }
            raw_draft: object | None = None
            try:
                if attempts and attempts[-1].decision == "supervisor_unavailable":
                    raw_draft = {"message": attempts[-1].client_draft}
                else:
                    raw_draft = self._draft_transport.draft(draft_payload)
                draft = ClientDraft.model_validate(raw_draft)
                if self._project_context:
                    # The model selects the requested scope; the program copies
                    # its interface verbatim. Supervisor reviews this final text,
                    # not an earlier draft without the canonical appendix.
                    by_name={u.name:u for u in self._registry.slots}
                    if len(draft.interface_names)!=len(set(draft.interface_names)) or any(name not in by_name for name in draft.interface_names):
                        raise ValueError('Unknown or duplicate requested interface name')
                    if draft.interface_names and self._project_context.get('context_protocol') != 'role-context.v3-elicitation':
                        blocks=[]
                        for name in draft.interface_names:
                            interface=by_name[name].test_interface.model_dump(mode='json')
                            blocks.append(name+' — agreed delivery interface:\n```json\n'+json.dumps(interface,ensure_ascii=False,indent=2)+'\n```')
                        draft=draft.model_copy(update={'message':draft.message+'\n\n'+'\n\n'.join(blocks)})
            except ClientSimulationError:
                raise
            except (LLMError, OSError) as error:
                raise ClientSimulationError(
                    f"Client provider call failed: {error}", attempts=attempts
                ) from error
            except Exception as error:
                reason = self._validation_reason(
                    "Client draft validation failed", error
                )
                record_attempt(
                    SupervisionAttempt(
                        attempt=attempt_number,
                        client_draft=self._raw_output_text(
                            raw_draft,
                            getattr(self._draft_transport, "last_trace", None),
                        ),
                        decision="invalid_client_output",
                        disclosed_ru_ids=[],
                        newly_disclosed_hidden_ru_ids=[],
                        triggered_ru_ids=[],
                        violations=["invalid_client_output"],
                        rewrite_instruction=(
                            (
                                'Return one valid JSON object with message (a complete, '
                                'nonempty natural-language Client reply), interface_names '
                                '(an empty array), and optional contract_conflict (null '
                                'unless authoritative sources conflict). No prose outside JSON. '
                                if self._project_context.get('context_protocol') == 'role-context.v3-elicitation'
                                else 'Follow the original private output schema: return one valid '
                                'JSON object with a complete nonempty message and interface_names '
                                'containing only the exact requested requirement names. '
                                'No prose outside JSON. '
                                if self._project_context.get('contract_version')
                                else 'Return one complete, nonempty natural-language Client reply. '
                            )
                            + 'Preserve supported substantive content and use the supplied '
                            'authoritative project facts. Say an answer is unspecified only '
                            'when that evidence does not define it.'
                        ),
                        reason=reason,
                        client_trace=deepcopy(
                            getattr(self._draft_transport, "last_trace", None)
                        ),
                        supervisor_trace=None,
                    )
                )
                continue

            supervisor_payload = {
                "schema_version": 1,
                "public_task": role_public_task,
                "conversation": history,
                "candidate_message": candidate_message,
                "question_atoms": question_atoms,
                "client_draft": draft.message,
                "client_conflict_report": draft.contract_conflict,
                "requirement_units": deepcopy(self._wire_units),
                "project_context": deepcopy(self._project_context),
                "supervision_protocol_version": SUPERVISION_PROTOCOL_VERSION,
            }
            raw_review: object | None = None
            client_trace = deepcopy(
                attempts[-1].client_trace
                if attempts and attempts[-1].decision == "supervisor_unavailable"
                else getattr(self._draft_transport, "last_trace", None)
            )
            try:
                raw_review = self._supervisor_transport.review(supervisor_payload)
                review = SupervisorReview.model_validate(raw_review)
                if 'contract_conflict' in review.violations:
                    record_attempt(SupervisionAttempt(
                        attempt=attempt_number, client_draft=draft.message,decision='revise',
                        disclosed_ru_ids=[],newly_disclosed_hidden_ru_ids=[],triggered_ru_ids=[],
                        violations=review.violations,rewrite_instruction=review.rewrite_instruction,
                        reason=review.reason,client_trace=client_trace,
                        supervisor_trace=deepcopy(getattr(self._supervisor_transport,'last_trace',None)),
                    ))
                    raise ClientSimulationError(
                        'Acceptance source and delivery agreement conflict; maintainer review required',
                        attempts=attempts, code='client.contract_conflict', retryable=False,
                    )
                review = self._normalize_approved_review(review, previous_hidden)
            except ClientSimulationError:
                raise
            except Exception as error:
                unavailable = isinstance(error, (LLMError, OSError))
                decision = "supervisor_unavailable" if unavailable else "invalid_supervisor_output"
                record_attempt(SupervisionAttempt(
                    attempt=attempt_number, client_draft=draft.message, decision=decision,
                    disclosed_ru_ids=[], newly_disclosed_hidden_ru_ids=[], triggered_ru_ids=[],
                    violations=[decision], rewrite_instruction=None,
                    reason=self._validation_reason("Supervisor review failed", error),
                    client_trace=client_trace,
                    supervisor_trace=deepcopy(getattr(self._supervisor_transport, "last_trace", None)),
                ))
                if unavailable:
                    raise ClientSimulationError(
                        f"Supervisor provider call failed: {error}", attempts=attempts
                    ) from error
                stop("Supervisor output exhausted; the frozen draft requires review",
                     "client.supervisor_exhausted")
            record_attempt(
                SupervisionAttempt(
                    attempt=attempt_number,
                    client_draft=draft.message,
                    decision=review.decision,
                    ru_annotations=review.ru_annotations,
                    disclosed_ru_ids=list(review.disclosed_ru_ids),
                    newly_disclosed_hidden_ru_ids=list(
                        review.newly_disclosed_hidden_ru_ids
                    ),
                    triggered_ru_ids=list(review.triggered_ru_ids),
                    violations=list(review.violations),
                    rewrite_instruction=review.rewrite_instruction,
                    reason=review.reason,
                    question_count=review.question_count,
                    relevant_question_count=review.relevant_question_count,
                    question_counts_by_ru=review.question_counts_by_ru,
                    followup_question_counts_by_ru=review.followup_question_counts_by_ru,
                    annotation_status=review.annotation_status,
                    annotation_errors=review.annotation_errors,
                    trigger_reason=review.reason,
                    triggered_question_atom_ids=list(
                        review.triggered_question_atom_ids
                    ),
                    question_atom_ids_by_ru=deepcopy(
                        review.question_atom_ids_by_ru
                    ),
                    client_trace=client_trace,
                    supervisor_trace=deepcopy(
                        getattr(self._supervisor_transport, "last_trace", None)
                    ),
                )
            )
            if review.decision == "approve":
                return SupervisedClientRender(
                    text=draft.message,
                    disclosed_ru_ids=list(review.disclosed_ru_ids),
                    newly_disclosed_hidden_ru_ids=list(
                        review.newly_disclosed_hidden_ru_ids
                    ),
                    attempts=attempts,
                )
            # The next iteration reads the persisted draft and concrete feedback.
            # The Client regenerates the complete reply; the Supervisor reviews it
            # again before any candidate-visible message is committed.

    @staticmethod
    def _validation_reason(prefix: str, error: Exception) -> str:
        detail = " ".join(str(error).split())
        return f"{prefix}: {detail}"[:2000]

    @staticmethod
    def _raw_output_text(raw: object | None, trace: object | None) -> str:
        if isinstance(raw, dict):
            message = raw.get("message")
            if isinstance(message, str):
                return message
        if isinstance(trace, dict):
            final_text = trace.get("final_text")
            if isinstance(final_text, str):
                return final_text[:8000]
        return repr(raw)[:8000]

    @staticmethod
    def _client_public_task(public_task: str) -> str:
        """Hide benchmark bookkeeping from the simulated Client.

        The Coding Agent still receives the exact task input.  The Client only
        needs the same human-facing facts, so strip generated RU headings while
        preserving the requirement text and agreed delivery interfaces.
        """

        text = re.sub(
            r"(?im)^# Initially disclosed (?:Requirement Units|requirements)\s*$",
            "# Initially disclosed requirements",
            public_task,
        )
        text = re.sub(r"(?im)^## RU-\d+:\s*", "## ", text)
        text = re.sub(
            r"\bRequirement Units?\b",
            lambda match: "requirements" if match.group(0).endswith("s") else "requirement",
            text,
            flags=re.IGNORECASE,
        )
        return text

    def _normalize_approved_review(
        self,
        review: SupervisorReview,
        previous_hidden: set[str],
    ) -> SupervisorReview:
        """Retain optional known disclosure diagnostics without controlling approval."""
        if review.decision != "approve":
            return review
        known = set(self._units_by_id)
        updates = {}
        errors = list(review.annotation_errors)
        for name in ["disclosed_ru_ids", "triggered_ru_ids", "newly_disclosed_hidden_ru_ids"]:
            ids = getattr(review, name)
            if set(ids) - known:
                errors.append(name + " contains unknown RUs; ignored")
            updates[name] = [ru for ru in ids if ru in known]
        updates["newly_disclosed_hidden_ru_ids"] = [
            ru for ru in updates["disclosed_ru_ids"]
            if not self._units_by_id[ru].initially_visible and ru not in previous_hidden
        ]
        # Disclosure is a required supervisor output, not an optional diagnostic:
        # a silently absent list is indistinguishable from "nothing was disclosed"
        # and would under-report hidden requirement recall.  Record it so the
        # metric can be reported as unavailable instead of as a zero.
        if not isinstance(getattr(review, "disclosed_ru_ids", None), list) or (
            "disclosed_ru_ids" not in (review.model_fields_set or set())
        ):
            errors.append("disclosed_ru_ids missing; disclosure for this turn is unknown")
        if review.question_counts_by_ru is not None and set(review.question_counts_by_ru) != known:
            errors.append("Per-RU question annotation coverage is invalid; counts are unknown")
            updates.update(question_count=None, relevant_question_count=None,
                           question_counts_by_ru=None, followup_question_counts_by_ru=None,
                           annotation_status="unavailable")
        updates["annotation_errors"] = errors
        return review.model_copy(update=updates)

    @staticmethod
    def _wire_unit(unit: RequirementRecord) -> dict[str, Any]:
        interface = getattr(unit, "test_interface", None)
        if interface is None:
            interface = getattr(unit, "interface_contract", None)
        interface_payload = (
            interface.model_dump(mode="json")
            if hasattr(interface, "model_dump")
            else deepcopy(interface)
        )
        return {
            "ru_id": unit.slot_id,
            "name": unit.name,
            "content": (
                getattr(unit, "requirement_text", None) or unit.prepared_answer
            ),
            "benchmark_visibility": (
                "visible" if unit.initially_visible else "hidden"
            ),
            "test_interface": interface_payload,
        }

    @classmethod
    def _wire_selection_unit(cls, unit: RequirementRecord) -> dict[str, Any]:
        """Build the private pre-draft matching view for one RU.

        The normalized behavior remains the disclosure authority.  Original
        source wording and optional annotation terms are supplied only to the
        internal Supervisor so it can resolve aliases used by the Coding
        Agent.  This context is never passed to the Client draft generator or
        rendered into candidate-visible conversation.
        """

        payload = cls._wire_unit(unit)
        source_quotes = [
            str(source.quote).strip()
            for source in getattr(unit, "provenance", [])
            if getattr(source, "quote", None) and str(source.quote).strip()
        ]
        matching_keywords = [
            str(keyword).strip()
            for keyword in getattr(unit, "matching_keywords", [])
            if str(keyword).strip()
        ]
        if source_quotes or matching_keywords:
            payload["private_matching_context"] = {
                "source_quotes": source_quotes,
                "matching_keywords": matching_keywords,
            }
        return payload














def render_requirement_disclosure(record: RequirementRecord) -> str:
    """Disclose RU content plus its agreed interface, never its hidden tests."""

    disclosure = getattr(record, "disclosure_text", None)
    if callable(disclosure):
        return str(disclosure())

    content = (getattr(record, "requirement_text", None) or record.prepared_answer).strip()
    interface = getattr(record, "test_interface", None)
    if interface is None:
        interface = getattr(record, "interface_contract", None)
    if interface is None:
        return content
    payload = (
        interface.model_dump(mode="json")
        if hasattr(interface, "model_dump")
        else interface
    )
    import json

    return (
        f"{content}\n\nAgreed delivery interface:\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )
