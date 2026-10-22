"""Strict core models for the SWE-Clar V4 pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class SessionPhase(str, Enum):
    DIALOGUE = "dialogue"
    FREEZING = "freezing"
    BRANCHED = "branched"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class BranchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class EvaluationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    INCOMPLETE = "incomplete"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class BudgetState(StrictModel):
    # Limits are nullable by design.  New Clarify runs leave both unset so the
    # Coding Agent owns termination; the counters below are telemetry only.
    # Numeric values remain readable for historical finite-budget sessions.
    question_atom_limit: int | None = Field(default=None, ge=0)
    dialogue_round_limit: int | None = Field(default=None, ge=1)
    question_atoms_used: int = Field(default=0, ge=0)
    dialogue_rounds_used: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def usage_must_not_exceed_limits(self) -> "BudgetState":
        if (
            self.question_atom_limit is not None
            and self.question_atoms_used > self.question_atom_limit
        ):
            raise ValueError("question_atoms_used cannot exceed question_atom_limit")
        if (
            self.dialogue_round_limit is not None
            and self.dialogue_rounds_used > self.dialogue_round_limit
        ):
            raise ValueError("dialogue_rounds_used cannot exceed dialogue_round_limit")
        return self


class OperationError(StrictModel):
    stage: str
    code: str
    message: str
    retryable: bool
    operation_id: str | None = None


class SlotValue(StrictModel):
    type: Literal["enum", "boolean", "number", "string", "set", "structured", "free_text"]
    canonical: Any
    accepted_aliases: list[Any] = Field(default_factory=list)
    comparator: dict[str, Any] = Field(min_length=1)
    required_facts: list[str] = Field(default_factory=list)


class SlotSource(StrictModel):
    source_type: Literal[
        "client_chat",
        "job_description",
        "client_attachment",
        "evaluation_criteria",
        "milestone_submission",
    ]
    source_id: str
    speaker: str | None = None
    quote: str | None = None
    content_hash: str | None = None
    locator: dict[str, Any] | None = None


class RequirementVisibility(StrictModel):
    """Whether one Requirement Unit is available before clarification."""

    label: Literal["visible", "hidden"]
    reason: str = Field(min_length=1)


class RequirementTestInterface(StrictModel):
    """Externally observable delivery agreement shared with the Coding Agent."""

    type: Literal["function", "command", "api", "c_api", "web_ui", "file"]
    entry: dict[str, Any]
    inputs: Any = None
    output: Any = None
    operations: list[str] = Field(default_factory=list)

    @field_validator("entry")
    @classmethod
    def entry_must_be_nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("test_interface.entry must not be empty")
        return value

    @model_validator(mode="after")
    def contract_must_describe_an_observable_surface(self) -> "RequirementTestInterface":
        if self.type == "c_api":
            if not self.operations:
                raise ValueError("c_api test_interface must list public operations")
        elif self.output is None or self.output == {} or self.output == "":
            raise ValueError("test_interface.output must describe the observable result")
        return self


class RequirementTestRef(StrictModel):
    """One hidden test owned by a Requirement Unit."""

    test_id: str = Field(pattern=r"^RU-[0-9]{3}-T[0-9]{2}$")
    file: str = Field(min_length=1)

    @field_validator("file")
    @classmethod
    def file_must_be_task_relative(cls, value: str) -> str:
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("Requirement Unit test files must be task-relative paths")
        return value


class RequirementUnit(StrictModel):
    """The annotation-facing Requirement Unit schema used by SWE-Clar task data.

    Compatibility properties intentionally preserve the existing execution
    engine while its persisted and API-facing contract moves from Slots to
    Requirement Units.  They are not serialized into ``requirement_units.yaml``.
    """

    ru_id: str = Field(pattern=r"^RU-[0-9]{3}$")
    name: str = Field(min_length=1)
    content: str = Field(min_length=1)
    requirement_category: Literal["core", "refinement"]
    source_visibility: Literal["visible", "hidden"]
    benchmark_visibility: Literal["visible", "hidden"]
    benchmark_visibility_reason: str = Field(min_length=1)
    audit_question: str = Field(min_length=1)
    matching_keywords: list[str] = Field(default_factory=list)
    test_interface: RequirementTestInterface | None
    evaluation: Literal["executable", "audit_only"] = "executable"
    tests: list[RequirementTestRef]
    pass_rule: Literal["all_tests_pass", "not_scored"]
    notes: str | None = None
    provenance: list[SlotSource] = Field(default_factory=list)

    @field_validator("matching_keywords")
    @classmethod
    def matching_keywords_must_be_nonblank(cls, value: list[str]) -> list[str]:
        if any(not keyword.strip() for keyword in value):
            raise ValueError("matching_keywords must contain only nonblank strings")
        return value

    @model_validator(mode="after")
    def evaluation_and_tests_are_consistent(self) -> "RequirementUnit":
        test_ids = [test.test_id for test in self.tests]
        if len(test_ids) != len(set(test_ids)):
            raise ValueError("Requirement Unit test IDs must be unique")
        if any(
            not test_id.startswith(f"{self.ru_id}-T") for test_id in test_ids
        ):
            raise ValueError("Requirement Unit test IDs must be scoped to their RU ID")
        if self.evaluation == "executable":
            if self.test_interface is None:
                raise ValueError("executable Requirement Units require a test_interface")
            if not self.tests:
                raise ValueError("executable Requirement Units require at least one test")
            if self.pass_rule != "all_tests_pass":
                raise ValueError("executable Requirement Units require all_tests_pass")
        elif self.tests or self.pass_rule != "not_scored":
            raise ValueError("audit_only Requirement Units require tests: [] and not_scored")
        return self

    # Read-only execution compatibility.  New files must use the fields above.
    @property
    def slot_id(self) -> str:
        return self.ru_id

    @property
    def initially_visible(self) -> bool:
        return self.benchmark_visibility == "visible"

    @property
    def initial_visibility(self) -> RequirementVisibility:
        """Compatibility view for callers that have not migrated yet."""

        return RequirementVisibility(
            label=self.benchmark_visibility,
            reason=self.benchmark_visibility_reason,
        )

    @property
    def requirement_role(self) -> Literal["core", "clarification_candidate"]:
        """Legacy read-only category name for older runtime consumers."""

        return (
            "core"
            if self.requirement_category == "core"
            else "clarification_candidate"
        )

    @property
    def visibility_reason(self) -> str:
        """Legacy read-only name for older runtime consumers."""

        return self.benchmark_visibility_reason

    @property
    def prepared_answer(self) -> str:
        return self.content

    @property
    def match_hints(self) -> list[str]:
        return self.matching_keywords

    @property
    def testability(self) -> Literal["executable", "audit_only"]:
        return self.evaluation

    @property
    def test_refs(self) -> list[str]:
        return [test.test_id for test in self.tests]

    @property
    def importance(self) -> Literal["important"]:
        return "important"

    @property
    def benchmark_role(self) -> Literal["hidden_slot", "public_slot"]:
        return "public_slot" if self.initially_visible else "hidden_slot"

    @property
    def temporal_origin(self) -> Literal["preexisting_private", "initially_public"]:
        return "initially_public" if self.initially_visible else "preexisting_private"

    @property
    def elicitable(self) -> bool:
        return not self.initially_visible

    @property
    def private_or_non_disclosable(self) -> bool:
        return False

    @property
    def runtime_public_sources(self) -> list[RuntimePublicSource]:
        return []

    @property
    def requirement_text(self) -> str:
        return self.content

    def disclosure_text(self) -> str:
        """Return exactly what becomes visible when this RU is disclosed."""

        import json

        interface = json.dumps(
            self.test_interface.model_dump(mode="json") if self.test_interface else None,
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{self.content}\n\nAgreed delivery interface:\n{interface}"


class RuntimePublicSource(StrictModel):
    """A candidate-visible source, distinct from private Client provenance."""

    source_type: Literal["task_prompt", "attachment_observation"]
    source_id: str
    quote: str | None = None
    content_hash: str | None = None
    locator: dict[str, Any] | None = None


class FormationEvidence(StrictModel):
    """Why a requirement is believed to have existed at intake time."""

    source_ids: list[str] = Field(default_factory=list)
    rationale: str
    adjudication_required: bool = False


class RequirementInterfaceContract(StrictModel):
    """Stable, behavior-facing entry point used to evaluate one Requirement Unit."""

    kind: Literal[
        "python_function",
        "typescript_function",
        "cli",
        "http",
        "file",
        "ui",
    ]
    entrypoint: str
    signature: str
    invocation: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    error_contract: str
    disclosure_policy: Literal["always_public", "follows_requirement_visibility"]


class SlotRecord(StrictModel):
    slot_id: str
    name: str
    audit_question: str
    importance: Literal["critical", "important", "minor"]
    slot_type: Literal[
        "hard_constraint",
        "soft_preference",
        "acceptance_criterion",
        "design_freedom",
    ] = "hard_constraint"
    latent_at_start: bool = True
    elicitable: bool = True
    private_or_non_disclosable: bool = False
    acceptable_values: list[Any] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    conflicts_or_supersedes: list[str] = Field(default_factory=list)
    temporal_origin: Literal[
        "preexisting_private",
        "initially_public",
        "discovered_during",
        "created_during",
        "unknown",
    ] = "preexisting_private"
    interaction_act: Literal[
        "request",
        "answer",
        "clarification",
        "correction",
        "preference_update",
        "scope_add",
        "scope_remove",
        "verification",
        "workflow",
    ] = "answer"
    contract_delta: Literal["none", "refine", "narrow", "expand", "replace"] = "refine"
    benchmark_role: Literal["hidden_slot", "public_slot"] = "hidden_slot"
    temporal_confidence: Literal["high", "medium", "low"] = "high"
    formation_evidence: FormationEvidence | None = None
    initially_visible: bool = False
    runtime_public_sources: list[RuntimePublicSource] = Field(default_factory=list)
    requirement_text: str | None = None
    interface_contract: RequirementInterfaceContract | None = None
    value: SlotValue
    prepared_answer: str
    match_hints: list[str] = Field(default_factory=list)
    provenance: list[SlotSource]
    testability: Literal["executable", "audit_only"]
    test_refs: list[str] = Field(default_factory=list)
    audit_only_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_backward_compatible_temporal_defaults(cls, data: Any) -> Any:
        """Keep legacy registries readable while making new annotations explicit."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        initially_visible = bool(normalized.get("initially_visible", False))
        if "temporal_origin" not in normalized:
            normalized["temporal_origin"] = (
                "initially_public" if initially_visible else "preexisting_private"
            )
        if "interaction_act" not in normalized:
            normalized["interaction_act"] = "request" if initially_visible else "answer"
        if "contract_delta" not in normalized:
            normalized["contract_delta"] = "none" if initially_visible else "refine"
        if "benchmark_role" not in normalized:
            normalized["benchmark_role"] = "public_slot" if initially_visible else "hidden_slot"
        return normalized


class SlotRegistry(StrictModel):
    schema_version: Literal[4] = 4
    task_id: str
    registry_version: str
    registry_status: Literal["validated", "structured_draft", "text_draft"]
    provenance_policy: Literal[
        "client_evidence",
        "evaluation_criteria_grounded",
    ] = "client_evidence"
    interface_contract_policy: Literal[
        "legacy_optional",
        "required_per_executable_unit",
    ] = "legacy_optional"
    slots: list[SlotRecord]

    def matcher_metadata(self) -> dict[str, Any]:
        """Return content-grounded metadata for the trusted Matcher."""

        return {
            "registry_version": self.registry_version,
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "name": slot.name,
                    "audit_question": slot.audit_question,
                    "content": slot.prepared_answer,
                    "initially_visible": slot.initially_visible,
                }
                for slot in self.slots
            ],
        }


class RequirementUnitRegistry(StrictModel):
    """Authoritative SWE-Clar Requirement Unit Registry."""

    schema_version: Literal[1] = 1
    task_id: str = Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    registry_version: str = Field(default="swe-clar", min_length=1)
    registry_status: Literal[
        "annotation_complete",
        "validated",
        "structured_draft",
        "text_draft",
    ] = "annotation_complete"
    disclosure_design: Literal[
        "source_faithful",
        "controlled_requirement_disclosure",
    ] = "source_faithful"
    # Optional task-level annotation context.  This describes which executable
    # slice was selected from a broader real job; it is not disclosed to the
    # Coding Agent and does not affect scoring.
    selected_scope: str | None = None
    requirement_units: list[RequirementUnit]

    @model_validator(mode="after")
    def ru_ids_are_unique(self) -> "RequirementUnitRegistry":
        ru_ids = [unit.ru_id for unit in self.requirement_units]
        if len(ru_ids) != len(set(ru_ids)):
            raise ValueError("Requirement Unit IDs must be unique")
        return self

    @property
    def slots(self) -> list[RequirementUnit]:
        """Compatibility projection for the existing dialogue and scorers."""

        return self.requirement_units

    def matcher_metadata(self) -> dict[str, Any]:
        """Return canonical content to the trusted semantic Matcher.

        ``matching_keywords`` remains an optional annotation aid but is not used
        by the production matching path.  Test interfaces and hidden tests stay
        outside this payload.
        """

        return {
            "registry_version": self.registry_version,
            "slots": [
                {
                    "slot_id": unit.ru_id,
                    "name": unit.name,
                    "audit_question": unit.audit_question,
                    "content": unit.content,
                    "initially_visible": unit.initially_visible,
                }
                for unit in self.requirement_units
            ],
        }


Registry = SlotRegistry | RequirementUnitRegistry
RequirementRecord = SlotRecord | RequirementUnit
