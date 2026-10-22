"""Durable workflow-checkpoint engine for the V4 Research MVP."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from .actions import ClientMessageAction, ReadyAction, parse_candidate_action
from .artifacts import ArtifactStore
from .audit import (
    AuditSchemaError,
    build_audit_trace_items,
    build_semantic_judge_payload,
    score_clarification,
    validate_audit_output,
    validate_semantic_audit_judgment,
)
from .canonical import digest_json
from .observations import candidate_observations
from .online_annotations import summarize_annotations
from .coding import CandidateCodingFailure, coding_terminal_status, score_coding
from .client import render_requirement_disclosure
from .dialogue import DialogueService, DialogueStateError
from .freeze import (
    AttachmentManifestItem,
    FrozenContext,
    create_branch_envelope,
    freeze_context,
    model_visible_frozen_context,
)
from .manifests import TestManifest
from .models import BudgetState, Registry, RequirementRecord
from .storage import RevisionConflict, SessionRepository


class CandidateTurn(Protocol):
    def __call__(self, context: dict[str, Any]) -> str: ...


class AuditTurn(Protocol):
    def __call__(self, context: dict[str, Any]) -> object: ...


class AuditJudge(Protocol):
    def __call__(self, context: dict[str, Any]) -> object: ...


class CodingStep(Protocol):
    def __call__(self, context: dict[str, Any]) -> dict[str, Any]: ...


class CodingEvaluator(Protocol):
    def __call__(self, context: dict[str, Any]) -> dict[str, Any]: ...


class StepEngineError(RuntimeError):
    pass


def _model_visible_dialogue_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project durable dialogue records to conversational evidence only.

    Researcher-visible records retain the complete Pi transcript, reasoning,
    workflow-tool attempts, matcher diagnostics and raw actions.  Those fields
    are not dialogue evidence and must never be fed back into the next model
    turn or frozen into the Audit/Coding prefix.
    """

    return [
        {
            key: deepcopy(message[key])
            for key in ("message_id", "role", "content", "timestamp")
            if key in message
        }
        for message in messages
        if isinstance(message, dict)
    ]


class StepEngine:
    """Create and advance a run through one durable workflow checkpoint.

    The checkpoint is a control-plane unit used for Manual/Auto/Retry and
    restart recovery. It is not an experimental definition of model work:
    one Coding checkpoint may contain a complete Pi session with many model
    turns and tool events, which are persisted separately in the trace.
    """

    TERMINAL = {"succeeded", "incomplete", "failed"}

    def __init__(
        self,
        *,
        repository: SessionRepository,
        artifacts: ArtifactStore,
        registry: Registry,
        manifest: TestManifest,
        dialogue_service_factory: Callable[[SessionRepository, Registry], DialogueService],
        candidate_turn: CandidateTurn,
        audit_turn: AuditTurn,
        audit_judge: AuditJudge | None = None,
        audit_judge_model: str | None = None,
        coding_step: CodingStep,
        coding_evaluator: CodingEvaluator,
        public_task: str,
        source_catalog: list[dict[str, Any]],
        attachments: list[AttachmentManifestItem],
        candidate_config_digest: str,
        run_contract: dict[str, Any] | None = None,
        official_expected_gate_ids_digest: str | None = None,
        verifier_digest: str | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
        oracle_project_readme: str = "",
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.registry = registry.model_copy(deep=True)
        self.manifest = manifest.model_copy(deep=True)
        self.dialogue_service_factory = dialogue_service_factory
        self.candidate_turn = candidate_turn
        self.audit_turn = audit_turn
        self.audit_judge = audit_judge
        self.audit_judge_model = audit_judge_model
        self.coding_step = coding_step
        self.coding_evaluator = coding_evaluator
        self.public_task = public_task
        self.oracle_project_readme = oracle_project_readme
        self.source_catalog = list(source_catalog)
        self.attachments = list(attachments)
        self.candidate_config_digest = candidate_config_digest
        self.run_contract = deepcopy(run_contract)
        self.official_expected_gate_ids_digest = official_expected_gate_ids_digest
        self.verifier_digest = verifier_digest
        self.clock = clock or _utc_now
        self.id_factory = id_factory or _new_id
        self.audit_only = bool(self.registry.slots) and not self.manifest.tests and all(
            slot.testability == "audit_only" for slot in self.registry.slots
        )

    def create_run(
        self,
        question_atom_limit: int | None = None,
        *,
        benchmark_mode: Literal["direct", "clarify", "oracle"] = "clarify",
        execution_mode: str = "manual",
        experiment_version: str = "V4.1.0",
        session_id: str | None = None,
        creation_request_digest: str | None = None,
    ) -> dict[str, Any]:
        if benchmark_mode not in {"direct", "clarify", "oracle"}:
            raise ValueError("benchmark_mode must be direct, clarify, or oracle")
        if benchmark_mode in {"direct", "oracle"} and question_atom_limit != 0:
            raise ValueError(
                "direct and oracle benchmark modes require question_atom_limit=0"
            )
        if benchmark_mode == "clarify" and question_atom_limit is not None:
            raise ValueError(
                "clarify benchmark mode is agent-controlled and requires no question limit"
            )
        budget = BudgetState(question_atom_limit=question_atom_limit)
        if execution_mode not in {"manual", "auto"}:
            raise ValueError("execution_mode must be manual or auto")
        created_at = self._now()
        session_id = session_id or sweclar_run_id(
            self.registry.task_id,
            benchmark_mode,
            created_at,
            self.id_factory("run"),
        )
        dialogue_active = benchmark_mode == "clarify"
        oracle_eligible_count = (
            len(self._oracle_eligible_slots())
            if benchmark_mode == "oracle"
            else 0
        )
        oracle_policy_version = (
            "all_applicable.content_and_interface.v2"
            if benchmark_mode == "oracle"
            else None
        )
        condition_config_digest = digest_json(
            {
                "schema_version": 1,
                "name": benchmark_mode,
                "dialogue_enabled": dialogue_active,
                "question_atom_limit": question_atom_limit,
                "dialogue_round_limit": budget.dialogue_round_limit,
                "oracle_policy_version": oracle_policy_version,
            }
        )
        initial = {
            "run_contract": deepcopy(self.run_contract),
            "schema_version": 4,
            "pipeline_version": 4,
            "experiment_version": experiment_version,
            "experiment_type": "sweclar_benchmark_run",
            "evaluation_scope": "audit_only" if self.audit_only else "coding",
            "dataset_ready": True,
            "run_id": session_id,
            "session_id": session_id,
            **({'creation_request_digest': creation_request_digest} if creation_request_digest else {}),
            "task_id": self.registry.task_id,
            "benchmark_mode": benchmark_mode,
            "benchmark_condition": {
                "schema_version": 1,
                "name": benchmark_mode,
                "dialogue_enabled": dialogue_active,
                "dialogue_round_limit": budget.dialogue_round_limit,
                "condition_config_digest": condition_config_digest,
                "oracle_policy_version": oracle_policy_version,
                "oracle_eligible_slot_count": oracle_eligible_count,
                "oracle_disclosed_slot_count": 0,
                "oracle_degenerate": (
                    benchmark_mode == "oracle"
                    and oracle_eligible_count == 0
                ),
            },
            "phase": "dialogue",
            "status": "running",
            "resolution_status": None,
            "evaluation_error": None,
            "evaluation_inputs": {
                "registry_version": self.registry.registry_version,
                "registry_digest": digest_json(
                    self.registry.model_dump(mode="json")
                ),
                "manifest_digest": digest_json(
                    self.manifest.model_dump(mode="json")
                ),
                **(
                    {
                        "official_expected_gate_ids_digest":
                            self.official_expected_gate_ids_digest
                    }
                    if self.official_expected_gate_ids_digest is not None
                    else {}
                ),
                **(
                    {"verifier_digest": self.verifier_digest}
                    if self.verifier_digest is not None
                    else {}
                ),
            },
            "created_at": created_at,
            "job_context": {
                "public_task": self.public_task,
                "attachments": [item.model_dump(mode="json") for item in self.attachments],
            },
            "budget": budget.model_dump(mode="json"),
            "cursor": "dialogue.candidate" if dialogue_active else "freezing",
            "execution": {
                "mode": execution_mode,
                "autorun": False,
                "stop_requested": False,
                "agent_step_count": 0,
                "next_sequence": 1,
            },
            "steps": [],
            "timeline": [
                {
                    "event_id": self.id_factory("event"),
                    "kind": "run.created",
                    "actor": "system",
                    "timestamp": created_at,
                    "body": {
                        "benchmark_mode": benchmark_mode,
                        "question_atom_limit": question_atom_limit,
                        "dialogue_round_limit": budget.dialogue_round_limit,
                        "execution_mode": execution_mode,
                    },
                }
            ],
            "dialogue": {
                "supervision_protocol_version": "semantic_review.v2",
                "messages": [],
                "exposure_ledger": [],
                "supervision_events": [],
                "pending_exchange": None,
                "pending_actor": "candidate" if dialogue_active else "none",
                "end_reason": (
                    None
                    if dialogue_active
                    else (
                        "direct_no_dialogue"
                        if benchmark_mode == "direct"
                        else "oracle_preloaded"
                    )
                ),
                "operation_error": None,
            },
            "errors": [],
            "frozen_context": None,
            "branches": {"audit": None, "coding": None},
        }
        self.repository.create_session(initial)
        return self.finish_initialization(session_id)

    def finish_initialization(self, session_id: str) -> dict[str, Any]:
        current = self.repository.get_session(session_id)
        self._check_run_contract(current)
        if current.get('cursor') == 'freezing':
            if current['benchmark_mode'] == 'oracle' and not any(
                item.get('kind') == 'oracle.evidence_injected' for item in current.get('timeline', [])
            ):
                self._inject_oracle_evidence(session_id)
            self._freeze(session_id)
        return self.repository.get_session(session_id)

    def step(self, session_id: str) -> dict[str, Any]:
        current = self.repository.get_session(session_id)
        self._check_run_contract(current)
        if current.get("status") in self.TERMINAL:
            return current
        if current.get("evaluation_error"):
            raise StepEngineError("run has a retryable evaluation error; retry it first")
        if current.get("dialogue", {}).get("operation_error"):
            raise StepEngineError("run has a retryable infrastructure error; retry it first")
        if any(step.get("status") == "failed_retryable" for step in current.get("steps", [])):
            raise StepEngineError("run has a retryable workflow checkpoint; retry it first")
        if any(step.get("status") == "running" for step in current.get("steps", [])):
            raise StepEngineError("run already has an unfinished workflow checkpoint")
        cursor = current.get("cursor")
        if cursor == "dialogue.candidate":
            return self._candidate_step(session_id)
        if cursor == "dialogue.client":
            return self._client_step(session_id)
        if cursor == "audit.agent":
            return self._audit_step(session_id)
        if cursor == "coding.agent":
            return self._coding_step(session_id)
        raise StepEngineError(f"run is not at an executable workflow cursor: {cursor!r}")

    def retry(self, session_id: str) -> dict[str, Any]:
        current = self.repository.get_session(session_id)
        self._check_run_contract(current)
        evaluation_error = current.get("evaluation_error")
        if evaluation_error:
            if not evaluation_error.get("retryable"):
                raise StepEngineError("run has no retryable operation")
            final_action = self._last_done_final_action(current)
            if final_action is None:
                raise StepEngineError(
                    "run has no completed Coding Agent final action to evaluate"
                )
            self._evaluate(session_id, final_action)
            return self.repository.get_session(session_id)
        error = current.get("dialogue", {}).get("operation_error")
        if not error:
            failed = next(
                (step for step in reversed(current.get("steps", [])) if step.get("status") == "failed_retryable"),
                None,
            )
            if failed is None:
                raise StepEngineError("run has no retryable operation")
            if (failed.get("error") or {}).get("code") == "audit.judge_invalid_output":
                checkpoint = failed.get("output") or {}
                raw_output = checkpoint.get("raw_output")
                try:
                    output = validate_audit_output(raw_output, self.registry)
                except AuditSchemaError as checkpoint_error:
                    raise StepEngineError(
                        "stored Audit Agent output is not a valid retry checkpoint"
                    ) from checkpoint_error
                audit_model_trace = checkpoint.get("model_trace")
                self._mark_latest_retryable_step_retried(session_id)
                return self._retry_audit_judge_step(
                    session_id,
                    output,
                    audit_model_trace=(
                        deepcopy(audit_model_trace)
                        if isinstance(audit_model_trace, dict)
                        else None
                    ),
                )
            pending_exchange = current.get("dialogue", {}).get("pending_exchange")
            if (
                pending_exchange is not None
                and current.get("cursor") == "dialogue.candidate"
            ):
                dialogue = self.dialogue_service_factory(
                    self.repository, self.registry
                )
                try:
                    pending = dialogue.resume_infrastructure(
                        session_id, retry=False
                    )
                except DialogueStateError:
                    return self.repository.get_session(session_id)
                if pending is None:
                    self._finish_latest_retryable_step(session_id, "succeeded")
                    self._patch(session_id, {"cursor": "dialogue.candidate"})
                else:
                    latest = self.repository.get_session(session_id)
                    self._patch(
                        session_id,
                        {
                            "cursor": "dialogue.client",
                            "timeline": [
                                *latest.get("timeline", []),
                                self._event(
                                    "matcher.completed",
                                    "matcher",
                                    {
                                        "operation_id": pending.operation_id,
                                        "atoms": [
                                            atom.model_dump(mode="json")
                                            for atom in (
                                                pending.atomic_questions or []
                                            )
                                        ],
                                    },
                                ),
                            ],
                        },
                    )
                    self._finish_latest_retryable_step(
                        session_id, "succeeded"
                    )
                return self.repository.get_session(session_id)
            self._mark_latest_retryable_step_retried(session_id)
            return self.step(session_id)
        if not error.get("retryable"):
            raise StepEngineError("run has no retryable operation")
        dialogue = self.dialogue_service_factory(self.repository, self.registry)
        try:
            pending = dialogue.resume_infrastructure(session_id, retry=True)
        except DialogueStateError:
            return self.repository.get_session(session_id)
        if pending is None:
            self._finish_latest_retryable_step(session_id, "succeeded")
            self._freeze(session_id)
        else:
            self._patch(
                session_id,
                {
                    "cursor": "dialogue.client",
                    "timeline": [
                        *self.repository.get_session(session_id).get("timeline", []),
                        self._event("matcher.completed", "matcher", {
                            "operation_id": pending.operation_id,
                            "atoms": [atom.model_dump(mode="json") for atom in (pending.atomic_questions or [])],
                        }),
                    ],
                },
            )
            self._finish_latest_retryable_step(session_id, "succeeded")
        return self.repository.get_session(session_id)

    def _check_run_contract(self, current: dict[str, Any]) -> None:
        if current.get("run_contract") != self.run_contract:
            raise StepEngineError(
                "run contract changed or is missing; restore the pinned code, data and "
                "model configuration, or create a new experiment"
            )

    def _candidate_step(self, session_id: str) -> dict[str, Any]:
        step_id = self._start_step(session_id, "dialogue", "coding_agent", "candidate_action")
        current = self.repository.get_session(session_id)
        candidate_trace = None
        try:
            raw_action = self.candidate_turn(
                {
                    "session_id": session_id,
                    "task_id": self.registry.task_id,
                    "public_task": self.public_task,
                    "attachments": [item.path for item in self.attachments],
                    "budget": current["budget"],
                    "candidate_observations": candidate_observations(current["dialogue"]["messages"]),
                    "messages": _model_visible_dialogue_messages(
                        current["dialogue"]["messages"]
                    ),
                    "workflow_contract": {
                        "message_client": (
                            "one natural Client-facing requirements conversation turn"
                        ),
                        "finish_clarification": "end the clarification phase",
                        "accepted_actions_per_turn": 1,
                    },
                }
            )
            candidate_trace = self._adapter_trace(self.candidate_turn)
            workflow_action = deepcopy(
                getattr(self.candidate_turn, "last_workflow_action", None)
            )
            action = parse_candidate_action(raw_action)
        except Exception as error:
            candidate_trace = candidate_trace or self._adapter_trace(
                self.candidate_turn
            )
            self._fail_step(
                session_id,
                step_id,
                "provider.refusal" if getattr(error, "provider_refusal", False) else "candidate.action_failed",
                error,
                retryable=not getattr(error, "provider_refusal", False),
                diagnostics={"model_trace": candidate_trace},
            )
            return self.repository.get_session(session_id)

        if isinstance(action, ReadyAction):
            message = {
                "message_id": self.id_factory("ready"),
                "role": "candidate",
                "content": "Clarification finished",
                "action": "ready",
                "workflow_action": "finish_clarification",
                "decision_summary": action.decision_summary,
                "decision_context": {
                    "visible_task": True,
                    "attachment_count": len(self.attachments),
                    "prior_dialogue_message_count": len(
                        current["dialogue"].get("messages", [])
                    ),
                    "termination_policy": "agent_controlled",
                },
                "raw_action": raw_action,
                "model_trace": candidate_trace,
                "timestamp": self._now(),
            }
            latest = self.repository.get_session(session_id)
            self._patch(session_id, {"dialogue": {
                "messages": [*latest["dialogue"].get("messages", []), message],
                "end_reason": "ready",
                "pending_actor": "none",
            }})
            self._finish_step(session_id, step_id, "succeeded", {
                "action": "ready",
                "workflow_action": workflow_action,
                "decision_summary": action.decision_summary,
                "raw": raw_action,
            })
            self._freeze(session_id)
            return self.repository.get_session(session_id)

        dialogue = self.dialogue_service_factory(self.repository, self.registry)
        dialogue.begin_ask(
            session_id,
            action,
            model_trace=candidate_trace,
        )
        try:
            pending = dialogue.resume_infrastructure(session_id)
        except DialogueStateError as error:
            self._fail_step(session_id, step_id, "dialogue.infrastructure_failed", error, retryable=True)
            return self.repository.get_session(session_id)
        if pending is None:
            self._finish_step(session_id, step_id, "succeeded", {"action": "message", "accepted": False})
            # A rejected historical finite-budget action must not create the
            # branch point. Current unlimited runs accept natural non-question
            # turns; only finish_clarification ends Clarify.
            self._patch(session_id, {"cursor": "dialogue.candidate"})
            return self.repository.get_session(session_id)
        latest = self.repository.get_session(session_id)
        self._patch(session_id, {
            "cursor": "dialogue.client",
            "timeline": [*latest.get("timeline", []), self._event(
                "dialogue.message.accepted", "coding_agent", {
                    "operation_id": pending.operation_id,
                    "message_id": pending.question_id,
                    "workflow_action": workflow_action,
                }
            )],
        })
        self._finish_step(session_id, step_id, "succeeded", {
            "action": workflow_action,
            "accepted": True,
        })
        return self.repository.get_session(session_id)

    def _client_step(self, session_id: str) -> dict[str, Any]:
        step_id = self._start_step(session_id, "dialogue", "client_agent", "client_answer")
        dialogue = self.dialogue_service_factory(self.repository, self.registry)
        try:
            message = dialogue.commit_client_response(session_id)
        except DialogueStateError as error:
            self._fail_step(session_id, step_id, error.code, error, retryable=error.retryable)
            return self.repository.get_session(session_id)
        latest = self.repository.get_session(session_id)
        self._patch(session_id, {"cursor": "dialogue.candidate"})
        self._finish_step(session_id, step_id, "succeeded", {
            "message_id": (message or {}).get("message_id"),
            "disclosed_ru_ids": (message or {}).get("disclosed_ru_ids", []),
            "newly_disclosed_hidden_ru_ids": (
                (message or {}).get("newly_disclosed_hidden_ru_ids", [])
            ),
            "supervision_attempt_count": len(
                (message or {}).get("supervision_attempts", [])
            ),
        })
        return self.repository.get_session(session_id)

    def _freeze(self, session_id: str) -> None:
        current = self.repository.get_session(session_id)
        if current.get("frozen_context"):
            return
        frozen = freeze_context(
            task_id=self.registry.task_id,
            benchmark_mode=current.get("benchmark_mode", "clarify"),
            question_atom_limit=current["budget"]["question_atom_limit"],
            dialogue_round_limit=current["budget"].get("dialogue_round_limit"),
            public_task=self.public_task,
            messages=_model_visible_dialogue_messages(
                current["dialogue"]["messages"]
            ),
            exposure_ledger=current["dialogue"]["exposure_ledger"],
            candidate_observation_history=candidate_observations(current["dialogue"]["messages"]),
            source_catalog=[source for source in self.source_catalog if source.get("candidate_visible") is True],
            attachments=self.attachments,
            candidate_config_digest=self.candidate_config_digest,
            artifacts=self.artifacts,
            clock=self.clock,
        )
        audit_envelope = create_branch_envelope(
            frozen,
            "audit",
            "Answer every Requirement Unit using the full pre-freeze context and your understanding.",
        )
        coding_envelope = create_branch_envelope(frozen, "coding", "Build the runnable delivery and satisfy the public contract.")
        latest = self.repository.get_session(session_id)
        self._patch(session_id, {
            "phase": "audit",
            "cursor": "audit.agent",
            "frozen_context": frozen.model_dump(mode="json"),
            "supervisor_metrics": summarize_annotations(self.registry, current["dialogue"], current.get("benchmark_mode","clarify")),
            "branch_point": {
                "schema_version": 1,
                "created_at": frozen.frozen_at,
                "prefix_digest": frozen.prefix_digest,
                "candidate_visible_evidence_digest": (
                    frozen.candidate_visible_evidence_digest
                ),
                "audit_and_coding_share_frozen_input": True,
                "audit_output_included_in_coding": False,
            },
            "branch_envelopes": {
                "audit": audit_envelope.model_dump(mode="json"),
                "coding": coding_envelope.model_dump(mode="json"),
            },
            "timeline": [*latest.get("timeline", []), self._event("context.frozen", "system", {
                "prefix_digest": frozen.prefix_digest,
                "end_reason": current["dialogue"].get("end_reason"),
            })],
        })

    def _inject_oracle_evidence(self, session_id: str) -> None:
        """Inject prepared Client evidence without invoking any Agent or Matcher."""

        current = self.repository.get_session(session_id)
        slots = self._oracle_eligible_slots()
        slot_ids = [slot.slot_id for slot in slots]
        hidden_slot_ids = [
            slot.slot_id for slot in slots if not slot.initially_visible
        ]
        public_slot_ids = [
            slot.slot_id for slot in slots if slot.initially_visible
        ]
        prepared_answers = [
            render_requirement_disclosure(slot) for slot in slots
        ]
        if self.oracle_project_readme:
            prepared_answers.append(
                'Full-information project documentation (Oracle condition only):\n'
                + self.oracle_project_readme
                + '\nIn this benchmark acceptance scripts and environment source are evaluator-only. '
                  'References to running public tests or reading infrastructure sources '
                  'do not grant access. Use the application contracts and your own checks.'
            )
        timestamp = self._now()
        client_message_id = self.id_factory("client_message")
        oracle_request_id = self.id_factory("oracle_request")
        client_message = {
            "message_id": client_message_id,
            "role": "client",
            "origin": "oracle",
            "content": "\n\n".join(prepared_answers),
            "timestamp": timestamp,
        }
        ledger_event = {
            "event_id": self.id_factory("exposure"),
            "origin": "oracle",
            "question_id": oracle_request_id,
            "question_message_id": oracle_request_id,
            "question_atom_ids": [],
            "client_message_id": client_message_id,
            "matched_hidden_slot_ids": list(hidden_slot_ids),
            "already_public_slot_ids": list(public_slot_ids),
            # Repeating a visible RU in Oracle's complete specification is not
            # a newly exposed hidden requirement.
            "revealed_slot_ids": list(hidden_slot_ids),
            "first_exposure_slot_ids": list(hidden_slot_ids),
            "answer_payload_hash": digest_json(
                {
                    "origin": "oracle",
                    "selected_answers": prepared_answers,
                }
            ),
            "matcher_version": "oracle.registry.v1",
            "revision": current["revision"] + 1,
            "timestamp": timestamp,
        }
        dialogue = current["dialogue"]
        self._patch(
            session_id,
            {
                "dialogue": {
                    "messages": [
                        *dialogue.get("messages", []),
                        client_message,
                    ],
                    "exposure_ledger": [
                        *dialogue.get("exposure_ledger", []),
                        ledger_event,
                    ],
                    "pending_exchange": None,
                    "pending_actor": "none",
                    "end_reason": "oracle_preloaded",
                    "operation_error": None,
                },
                "benchmark_condition": {
                    **current["benchmark_condition"],
                    "oracle_disclosed_slot_count": len(slot_ids),
                },
                "timeline": [
                    *current.get("timeline", []),
                    self._event(
                        "oracle.evidence_injected",
                        "system",
                        {
                            "client_message_id": client_message_id,
                            "revealed_slot_ids": slot_ids,
                        },
                    ),
                ],
            },
        )

    def _oracle_eligible_slots(self) -> list[RequirementRecord]:
        """Return every disclosable RU that applies at task intake."""

        return [
            slot
            for slot in self.registry.slots
            if (
                not slot.private_or_non_disclosable
                and slot.temporal_origin in {
                    "preexisting_private",
                    "initially_public",
                }
                and bool(slot.prepared_answer.strip())
            )
        ]

    def _audit_step(self, session_id: str) -> dict[str, Any]:
        step_id = self._start_step(session_id, "audit", "audit_agent", "audit_answer")
        current = self.repository.get_session(session_id)
        frozen = FrozenContext.model_validate(current["frozen_context"])
        envelope = current["branch_envelopes"]["audit"]
        raw = None
        audit_model_trace = None
        try:
            self._assert_branch_starts_from_freeze(current, "audit", frozen)
            raw = self.audit_turn({
                "session_id": session_id,
                "frozen_context": model_visible_frozen_context(frozen),
                "branch": envelope,
                "audit_questions": [
                    {"ru_id": slot.slot_id, "question": slot.audit_question}
                    for slot in self.registry.slots
                ],
            })
            audit_model_trace = self._adapter_trace(self.audit_turn)
            output = validate_audit_output(raw, self.registry)
        except Exception as error:
            audit_model_trace = audit_model_trace or self._adapter_trace(
                self.audit_turn
            )
            protocol_error = (
                isinstance(error, AuditSchemaError)
                or "must call submit_audit_answers" in str(error)
            )
            self._fail_step(
                session_id,
                step_id,
                (
                    "audit.agent_invalid_output"
                    if protocol_error
                    else "audit.agent_failed"
                ),
                error,
                retryable=not protocol_error,
                diagnostics={
                    "raw_output": deepcopy(raw),
                    "model_trace": audit_model_trace,
                },
            )
            return self.repository.get_session(session_id)
        return self._complete_audit_step(
            session_id,
            step_id,
            output,
            audit_model_trace=audit_model_trace,
            current=current,
            frozen=frozen,
            envelope=envelope,
        )

    def _retry_audit_judge_step(
        self,
        session_id: str,
        output: object,
        *,
        audit_model_trace: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Retry only the fixed judge while preserving Audit Agent output."""

        step_id = self._start_step(
            session_id,
            "audit",
            "audit_judge",
            "semantic_judgment",
        )
        current = self.repository.get_session(session_id)
        frozen = FrozenContext.model_validate(current["frozen_context"])
        envelope = current["branch_envelopes"]["audit"]
        return self._complete_audit_step(
            session_id,
            step_id,
            output,
            audit_model_trace=audit_model_trace,
            current=current,
            frozen=frozen,
            envelope=envelope,
        )

    def _complete_audit_step(
        self,
        session_id: str,
        step_id: str,
        output: object,
        *,
        audit_model_trace: dict[str, Any] | None,
        current: dict[str, Any],
        frozen: FrozenContext,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Score one immutable Audit Agent answer set and advance the Run."""

        judgment = None
        judge_trace = None
        if self.audit_judge is not None:
            try:
                judgment = validate_semantic_audit_judgment(
                    self.audit_judge(
                        build_semantic_judge_payload(
                            output,
                            self.registry,

                        )
                    ),
                    self.registry,
                )
                judge_trace = self._adapter_trace(self.audit_judge)
            except Exception as error:
                judge_trace = self._adapter_trace(self.audit_judge)
                self._fail_step(
                    session_id,
                    step_id,
                    "audit.judge_invalid_output",
                    error,
                    retryable=True,
                    diagnostics={
                        "raw_output": output.model_dump(mode="json"),
                        "model_trace": audit_model_trace,
                        "judge_trace": judge_trace,
                    },
                )
                return self.repository.get_session(session_id)
        metrics = score_clarification(
            output,
            self.registry,
            current["dialogue"]["exposure_ledger"],
            question_atoms_used=current["budget"]["question_atoms_used"],
            benchmark_mode=current.get("benchmark_mode", "clarify"),
            semantic_judgment=judgment,
            judge_model=self.audit_judge_model,
        )
        judgment_document = (
            judgment.model_dump(mode="json") if judgment is not None else None
        )
        audit_items = build_audit_trace_items(output, self.registry, judgment)
        judge_document = (
            {
                "role": "fixed_semantic_judge",
                "model": self.audit_judge_model,
                "scoring_basis": "semantic_content_only",
                "source_refs_scored": False,
                "frozen_evidence_checked": False,
            }
            if judgment is not None
            else None
        )
        latest = self.repository.get_session(session_id)
        terminal_patch = (
            {
                "phase": "completed",
                "status": "succeeded",
                "resolution_status": None,
                "cursor": "completed",
                "completed_at": self._now(),
            }
            if self.audit_only
            else {"phase": "coding", "cursor": "coding.agent"}
        )
        timeline = [
            *latest.get("timeline", []),
            self._event("audit.completed", "audit_agent", {
                "answers": output.model_dump(mode="json")["answers"],
                "model_trace": audit_model_trace,
                "items": audit_items,
                "judgment": judgment_document,
                "judge_trace": judge_trace,
                "judge": judge_document,
                "metrics": metrics.model_dump(mode="json"),
            }),
        ]
        if self.audit_only:
            timeline.append(self._event("run.completed", "system", {
                "evaluation_scope": "audit_only",
                "coding_evaluation": "not_applicable",
            }))
        self._patch(session_id, {
            **terminal_patch,
            "branches": {"audit": {
                "base_prefix_digest": envelope["base_prefix_digest"],
                "started_from_frozen_at": frozen.frozen_at,
                "output": output.model_dump(mode="json"),
                "model_trace": audit_model_trace,
                "items": audit_items,
                "judgment": judgment_document,
                "judge_trace": judge_trace,
                "judge": judge_document,
                "metrics": metrics.model_dump(mode="json"),
            }},
            "timeline": timeline,
        })
        self._finish_step(session_id, step_id, "succeeded", {
            "answer_count": len(output.answers),
            "judge_model": self.audit_judge_model,
        })
        return self.repository.get_session(session_id)

    @staticmethod
    def _adapter_trace(adapter: object) -> dict[str, Any] | None:
        trace = getattr(adapter, "last_trace", None)
        return deepcopy(trace) if isinstance(trace, dict) else None

    def _coding_step(self, session_id: str) -> dict[str, Any]:
        step_id = self._start_step(session_id, "coding", "coding_agent", "coding_action")
        current = self.repository.get_session(session_id)
        frozen = FrozenContext.model_validate(current["frozen_context"])
        try:
            self._assert_branch_starts_from_freeze(current, "coding", frozen)
            visible_coding_session = self._model_visible_coding_session(current)
            if "audit" in visible_coding_session.get("branches", {}):
                raise StepEngineError("Coding input must not contain Audit branch output")
            result = self.coding_step({
                "session": visible_coding_session,
                "frozen_context": model_visible_frozen_context(frozen),
                "branch": current["branch_envelopes"]["coding"],
                "basic_delivery_contract": self.manifest.basic_delivery_contract,
            })
        except CandidateCodingFailure as error:
            self._fail_step(
                session_id, step_id, error.code, error,
                retryable=False, diagnostics=error.diagnostics,
            )
            return self.repository.get_session(session_id)
        except Exception as error:
            self._fail_step(session_id, step_id, "coding.agent_failed", error, retryable=True)
            return self.repository.get_session(session_id)
        latest = self.repository.get_session(session_id)
        coding_branch = dict(latest.get("branches", {}).get("coding") or {})
        actions = [*coding_branch.get("actions", []), result]
        coding_branch.update({
            "base_prefix_digest": current["branch_envelopes"]["coding"]["base_prefix_digest"],
            "started_from_frozen_at": coding_branch.get(
                "started_from_frozen_at", frozen.frozen_at
            ),
            "audit_output_included": False,
            "actions": actions,
            "delivery_session_id": result.get("delivery_session_id") or coding_branch.get("delivery_session_id"),
            # Live Pi progress is a replaceable read projection. Once the
            # complete action is durable, the action transcript becomes the
            # sole canonical Coding trace for this checkpoint.
            "live_session": None,
        })
        self._patch(session_id, {
            "branches": {"coding": coding_branch},
            "timeline": [*latest.get("timeline", []), self._event("coding.action", "coding_agent", result)],
        })
        self._finish_step(session_id, step_id, "succeeded", {
            "action_type": result.get("action_type"), "done": bool(result.get("done"))
        })
        if result.get("done"):
            self._evaluate(session_id, result)
        return self.repository.get_session(session_id)

    @staticmethod
    def _assert_branch_starts_from_freeze(
        run: dict[str, Any],
        branch: Literal["audit", "coding"],
        frozen: FrozenContext,
    ) -> None:
        envelope = (run.get("branch_envelopes") or {}).get(branch) or {}
        if envelope.get("base_prefix_digest") != frozen.prefix_digest:
            raise StepEngineError(
                f"{branch} branch does not start from the frozen context"
            )

    @staticmethod
    def _model_visible_coding_session(run: dict[str, Any]) -> dict[str, Any]:
        coding = run.get("branches", {}).get("coding") or {}
        return deepcopy(
            {
                "schema_version": run.get("schema_version"),
                "pipeline_version": run.get("pipeline_version"),
                "session_id": run.get("session_id"),
                "task_id": run.get("task_id"),
                "phase": run.get("phase"),
                "created_at": run.get("created_at"),
                "branches": {
                    "coding": {
                        "base_prefix_digest": coding.get("base_prefix_digest"),
                        "actions": coding.get("actions", []),
                        "delivery_session_id": coding.get("delivery_session_id"),
                    }
                },
            }
        )

    def _evaluate(self, session_id: str, final_action: dict[str, Any]) -> None:
        self._patch(
            session_id,
            {
                "phase": "evaluating",
                "status": "running",
                "resolution_status": None,
                "cursor": "evaluating",
                "completed_at": None,
            },
        )
        try:
            evaluation = self.coding_evaluator({"session": self.repository.get_session(session_id), "final_action": final_action})
            test_results = evaluation.get("test_results", {})
            official_evaluation = (
                evaluation
                if any(
                    key in evaluation
                    for key in (
                        "official_reward",
                        "official_gates",
                        "official_verifier",
                    )
                )
                else None
            )
            metrics = score_coding(
                test_results,
                self.manifest,
                self.registry,
                official_evaluation=official_evaluation,
            )
        except Exception as error:
            self._record_evaluation_error(
                session_id, "evaluator.failed", str(error), retryable=True
            )
            return
        latest = self.repository.get_session(session_id)
        coding_branch = dict(latest["branches"].get("coding") or {})
        coding_branch.update({"result": evaluation, "metrics": metrics.model_dump(mode="json")})
        evaluation_error = None
        errors = list(latest.get("errors", []))
        if metrics.evaluation_incomplete:
            evaluation_error = {
                "stage": "evaluating",
                "code": "evaluator.incomplete",
                "message": "trusted evaluator returned incomplete results",
                "retryable": True,
            }
            if not errors or errors[-1] != evaluation_error:
                errors.append(evaluation_error)
        self._patch(session_id, {
            "phase": "completed",
            "status": coding_terminal_status(metrics),
            "resolution_status": metrics.resolution_status,
            "evaluation_error": evaluation_error,
            "cursor": "completed",
            "completed_at": self._now(),
            "branches": {"coding": coding_branch},
            "errors": errors,
            "timeline": [*latest.get("timeline", []), self._event("evaluation.completed", "evaluator", {
                "test_results": test_results,
                "metrics": metrics.model_dump(mode="json"),
            })],
        })

    def _start_step(self, session_id: str, phase: str, actor: str, action_type: str) -> str:
        current = self.repository.get_session(session_id)
        step_id = self.id_factory("step")
        sequence = current.get("execution", {}).get("next_sequence", len(current.get("steps", [])) + 1)
        step = {
            "step_id": step_id,
            "sequence": sequence,
            "phase": phase,
            "actor": actor,
            "action_type": action_type,
            "status": "running",
            "operation_id": self.id_factory("operation"),
            "started_at": self._now(),
            "completed_at": None,
            "output": None,
            "error": None,
        }
        self._patch(session_id, {
            "steps": [*current.get("steps", []), step],
            "execution": {
                "next_sequence": sequence + 1,
                "agent_step_count": current.get("execution", {}).get("agent_step_count", 0) + 1,
            },
        })
        return step_id

    def _finish_step(self, session_id: str, step_id: str, status: str, output: dict[str, Any]) -> None:
        current = self.repository.get_session(session_id)
        steps = [dict(step) for step in current.get("steps", [])]
        for step in steps:
            if step["step_id"] == step_id:
                step.update(status=status, output=output, completed_at=self._now())
                # ``live_session`` is only a replaceable projection while a
                # Pi Coding checkpoint is running.  The completed action now
                # owns the authoritative, lossless transcript, so retaining
                # the live copy here duplicates several megabytes of trace in
                # every terminal Run and makes subsequent status reads and
                # SQLite rewrites progressively more expensive.
                step.pop("live_session", None)
                break
        self._patch(session_id, {"steps": steps})

    def _finish_latest_retryable_step(self, session_id: str, status: str) -> None:
        current = self.repository.get_session(session_id)
        steps = [dict(step) for step in current.get("steps", [])]
        for step in reversed(steps):
            if step.get("status") == "failed_retryable":
                step.update(status=status, completed_at=self._now(), error=None)
                break
        self._patch(session_id, {"steps": steps})

    def _mark_latest_retryable_step_retried(self, session_id: str) -> None:
        """Close a failed attempt before creating a retry checkpoint."""

        current = self.repository.get_session(session_id)
        steps = [dict(step) for step in current.get("steps", [])]
        for step in reversed(steps):
            if step.get("status") == "failed_retryable":
                step.update(status="retried", retried_at=self._now())
                break
        self._patch(session_id, {"steps": steps})

    def _fail_step(
        self,
        session_id: str,
        step_id: str,
        code: str,
        error: Exception,
        *,
        retryable: bool,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        current = self.repository.get_session(session_id)
        if getattr(error, 'provider_refusal', False):
            code, retryable = 'provider.refusal', False
        safe_error = {"stage": current.get("cursor", "unknown"), "code": code, "message": str(error), "retryable": retryable}
        steps = [dict(step) for step in current.get("steps", [])]
        for step in steps:
            if step["step_id"] == step_id:
                step.update(status="failed_retryable" if retryable else "failed_terminal", error=safe_error, completed_at=self._now())
                if diagnostics is not None:
                    step["output"] = deepcopy(diagnostics)
                break
        errors = list(current.get("errors", []))
        if not errors or errors[-1] != safe_error:
            errors.append(safe_error)
        patch: dict[str, Any] = {"steps": steps, "errors": errors}
        if not retryable:
            patch.update({"status": "failed", "completed_at": self._now()})
        self._patch(session_id, patch)

    def _record_evaluation_error(
        self,
        session_id: str,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        current = self.repository.get_session(session_id)
        safe_error = {
            "stage": "evaluating",
            "code": code,
            "message": message,
            "retryable": retryable,
        }
        errors = list(current.get("errors", []))
        if not errors or errors[-1] != safe_error:
            errors.append(safe_error)
        self._patch(session_id, {
            "status": "running" if retryable else "failed",
            "evaluation_error": safe_error,
            "errors": errors,
        })

    @staticmethod
    def _last_done_final_action(run: dict[str, Any]) -> dict[str, Any] | None:
        coding_branch = run.get("branches", {}).get("coding") or {}
        for action in reversed(coding_branch.get("actions", [])):
            if isinstance(action, dict) and action.get("done") is True:
                return dict(action)
        return None

    def _event(self, kind: str, actor: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"event_id": self.id_factory("event"), "kind": kind, "actor": actor, "timestamp": self._now(), "body": body}

    def _patch(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        while True:
            current = self.repository.get_session(session_id)
            try:
                return self.repository.compare_and_swap(session_id, current["revision"], patch)
            except RevisionConflict:
                continue

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("step engine clock must return a timezone-aware datetime")
        return value.astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(kind: str) -> str:
    return f"{kind}-{uuid4().hex}"


def sweclar_run_id(
    task_id: str,
    benchmark_mode: str,
    created_at: str,
    entropy: str,
) -> str:
    """Build the canonical, readable SWE-Clar Run ID.

    Format: ``SWECLAR-RUN-<task-scope>-<MODE>-<UTC timestamp>-<8 hex>``.
    The Task ID remains authoritative; stripping its leading ``SWECLAR-`` avoids
    the redundant ``SWECLAR-RUN-SWECLAR-...`` rendering while preserving provenance.
    """

    task_scope = task_id.removeprefix("SWECLAR-")
    task_scope = re.sub(r"[^A-Za-z0-9]+", "-", task_scope).strip("-").upper()
    mode = re.sub(r"[^A-Za-z0-9]+", "-", benchmark_mode).strip("-").upper()
    moment = datetime.fromisoformat(created_at).astimezone(UTC)
    timestamp = moment.strftime("%Y%m%dT%H%M%SZ")
    suffix = sha256(entropy.encode("utf-8")).hexdigest()[:8].upper()
    return f"SWECLAR-RUN-{task_scope}-{mode}-{timestamp}-{suffix}"
