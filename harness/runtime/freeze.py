"""Minimal immutable evidence freeze for the single-job Research MVP."""

from __future__ import annotations
from .observations import textual_observations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable, Literal

from pydantic import Field

from .artifacts import ArtifactStore
from .canonical import digest_json
from .models import StrictModel


class AttachmentManifestItem(StrictModel):
    attachment_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FrozenContext(StrictModel):
    schema_version: Literal[4] = 4
    task_id: str
    benchmark_mode: Literal["direct", "clarify", "oracle"] = "clarify"
    question_atom_limit: int | None = Field(default=None, ge=0)
    dialogue_round_limit: int | None = Field(default=None, ge=1)
    evidence: dict[str, Any]
    candidate_visible_evidence_digest: str | None = None
    prefix_digest: str
    artifact_digest: str
    frozen_at: str


class BranchEnvelope(StrictModel):
    branch: Literal["audit", "coding"]
    base_prefix_digest: str
    branch_instruction: str
    branch_instruction_digest: str
    tool_permissions: list[str]


def freeze_context(
    *,
    task_id: str,
    question_atom_limit: int | None,
    dialogue_round_limit: int | None = None,
    public_task: str,
    messages: list[dict[str, Any]],
    exposure_ledger: list[dict[str, Any]],
    source_catalog: list[dict[str, Any]],
    attachments: list[AttachmentManifestItem],
    candidate_config_digest: str,
    artifacts: ArtifactStore,
    benchmark_mode: Literal["direct", "clarify", "oracle"] = "clarify",
    clock: Callable[[], datetime] | None = None,
    candidate_observation_history: list[dict[str, Any]] | None = None,
) -> FrozenContext:
    """Persist the semantic prefix; timestamps never affect its digest."""

    semantic = {
        "schema_version": 4,
        "task_id": task_id,
        "benchmark_mode": benchmark_mode,
        "question_atom_limit": question_atom_limit,
        "dialogue_round_limit": dialogue_round_limit,
        "public_task": public_task,
        "candidate_observations": textual_observations(candidate_observation_history or []),
        "messages": messages,
        "exposure_ledger": exposure_ledger,
        "source_catalog": source_catalog,
        "attachments": [item.model_dump(mode="json") for item in attachments],
        "candidate_config_digest": candidate_config_digest,
    }
    artifact = artifacts.put_json(semantic)
    candidate_visible_evidence_digest = digest_json(
        _model_visible_evidence(semantic)
    )
    frozen_at = _timestamp((clock or _utc_now)())
    return FrozenContext(
        task_id=task_id,
        benchmark_mode=benchmark_mode,
        question_atom_limit=question_atom_limit,
        dialogue_round_limit=dialogue_round_limit,
        evidence=semantic,
        candidate_visible_evidence_digest=candidate_visible_evidence_digest,
        prefix_digest=artifact.digest,
        artifact_digest=artifact.digest,
        frozen_at=frozen_at,
    )


def model_visible_frozen_context(frozen: FrozenContext) -> dict[str, Any]:
    """Project a frozen prefix to evidence that either model branch may see."""

    evidence = frozen.evidence
    visible_evidence = _model_visible_evidence(evidence)
    return {
        "schema_version": frozen.schema_version,
        "task_id": frozen.task_id,
        "question_atom_limit": frozen.question_atom_limit,
        "dialogue_round_limit": frozen.dialogue_round_limit,
        "candidate_visible_evidence_digest": (
            frozen.candidate_visible_evidence_digest
            or digest_json(visible_evidence)
        ),
        "prefix_digest": frozen.prefix_digest,
        "frozen_at": frozen.frozen_at,
        "evidence": visible_evidence,
    }


def _model_visible_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return the exact evidence projection hashed and sent to model branches."""

    messages = [
        {
            key: deepcopy(message[key])
            for key in ("message_id", "role", "content", "timestamp")
            if key in message
        }
        for message in evidence.get("messages", [])
        if isinstance(message, dict)
    ]
    return deepcopy(
        {
            "public_task": evidence.get("public_task", ""),
            "candidate_observations": evidence.get("candidate_observations", []),
            "messages": messages,
            "source_catalog": evidence.get("source_catalog", []),
            "attachments": evidence.get("attachments", []),
        }
    )


def create_branch_envelope(
    frozen: FrozenContext,
    branch: Literal["audit", "coding"],
    instruction: str,
) -> BranchEnvelope:
    permissions = (
        ["read", "submit_audit_answers"]
        if branch == "audit"
        else ["read", "bash", "edit", "write", "submit_delivery"]
    )
    return BranchEnvelope(
        branch=branch,
        base_prefix_digest=frozen.prefix_digest,
        branch_instruction=instruction,
        branch_instruction_digest=digest_json({"branch": branch, "instruction": instruction}),
        tool_permissions=permissions,
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("freeze clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)
