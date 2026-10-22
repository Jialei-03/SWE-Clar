"""Slot-registry loading and source-backed validation."""

import json
import hashlib
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .layout import requirements_path, input_path
from .manifests import TestManifest, ValidationIssue, validate_test_manifest
from .models import Registry, RequirementUnit, RequirementUnitRegistry


CLIENT_PROVENANCE_SOURCES = {"client_chat", "job_description", "client_attachment"}
CRITERIA_PROVENANCE_SOURCES = {"evaluation_criteria"}
DELIVERY_PROVENANCE_SOURCES = {"milestone_submission"}
RUNTIME_PUBLIC_SOURCE_TYPES = {"task_prompt", "attachment_observation"}
COMPARATOR_REQUIRED_KEYS = {
    "enum": {"alias_normalization"},
    "boolean": {"accepted_tokens"},
    "number": {"unit", "absolute_tolerance", "relative_tolerance", "minimum", "maximum"},
    "set": {"allow_extra_elements"},
    "structured": {"required_fields", "optional_fields", "additional_properties", "fields"},
}
STRING_COMPARATOR_KEYS = {"unicode", "case", "whitespace", "punctuation", "regex"}
AUDIT_YES_NO_PATTERN = re.compile(
    r"(?:^|[,;:]\s+|\band\s+)(?:is|are|should|does|do|can|will|must|has|have|was|were)\b",
    re.IGNORECASE,
)
AUDIT_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])",
    re.IGNORECASE,
)


class SourceIndex(dict[str, dict[str, Any]]):
    """Source records with duplicate stable IDs retained for validation."""

    def __init__(self) -> None:
        super().__init__()
        self.duplicate_ids: set[str] = set()


def _issue(
    code: str,
    message: str,
    *,
    slot_id: str | None = None,
    source_id: str | None = None,
    test_id: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="error",
        blocking=True,
        message=message,
        slot_id=slot_id,
        source_id=source_id,
        test_id=test_id,
    )


def load_registry(task_dir: Path) -> RequirementUnitRegistry:
    """Load the authoritative Requirement Unit task definition."""

    requirement_path = requirements_path(task_dir)
    if requirement_path.is_file():
        with requirement_path.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
        if not isinstance(document, Mapping):
            raise ValueError(f"{requirement_path}: expected a YAML mapping")
        normalized = dict(document)
        # Annotation files intentionally contain only task data.  Operational
        # identity and policy are derived by the platform so annotators do not
        # have to maintain schema/status/version boilerplate.
        if "registry_version" not in normalized:
            canonical = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            normalized["registry_version"] = (
                "sha256:" + hashlib.sha256(canonical).hexdigest()
            )
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("registry_status", "annotation_complete")
        if "disclosure_design" not in normalized:
            input_path = input_path(task_dir)
            input_design = None
            if input_path.is_file():
                try:
                    input_document = yaml.safe_load(input_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, yaml.YAMLError):
                    input_document = None
                if isinstance(input_document, Mapping):
                    input_design = input_document.get("design")
            normalized["disclosure_design"] = (
                input_design
                if input_design in {
                    "source_faithful",
                    "controlled_requirement_disclosure",
                }
                else (
                    "controlled_requirement_disclosure"
                    if input_path.is_file()
                    else "source_faithful"
                )
            )
        return RequirementUnitRegistry.model_validate(normalized)
    raise FileNotFoundError(f"{requirement_path}: task definition does not exist")


def load_source_index(task_dir: Path) -> SourceIndex:
    """Index original source JSONL records by their stable source ID."""
    index = SourceIndex()
    for path in sorted((task_dir / "sources").glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    source_id = record.get("source_id", record.get("id"))
                    if source_id:
                        if source_id in index:
                            index.duplicate_ids.add(source_id)
                        else:
                            index[source_id] = record
    return index


def _record_for(source_index: Mapping[str, Any], source_id: str) -> Mapping[str, Any] | None:
    record = source_index.get(source_id)
    return record if isinstance(record, Mapping) else None


def _value(source: Any, field: str) -> Any:
    return source.get(field) if isinstance(source, Mapping) else getattr(source, field, None)


def _is_nonblank_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_normalizable_phrase(value: Any) -> bool:
    return _is_nonblank_string(value) and bool(
        re.sub(r"[^a-z0-9]+", "", value.casefold())
    )


def audit_question_quality_codes(question: str, answer: Any) -> list[str]:
    """Return blocking Audit-question defects detectable without an LLM.

    Audit prompts must elicit a description instead of offering a yes/no guess.
    They also must not repeat numeric answer values: otherwise an Agent can copy
    the prompt without having recovered the underlying Requirement Unit.
    """

    codes: list[str] = []
    normalized_question = question.strip()
    if AUDIT_YES_NO_PATTERN.search(normalized_question):
        codes.append("not_open_ended")
    if isinstance(answer, str):
        question_numbers = {
            re.sub(r"\s+", "", item.casefold())
            for item in AUDIT_NUMBER_PATTERN.findall(normalized_question)
        }
        answer_numbers = {
            re.sub(r"\s+", "", item.casefold())
            for item in AUDIT_NUMBER_PATTERN.findall(answer)
        }
        if question_numbers & answer_numbers:
            codes.append("leaks_numeric_answer")
    return codes


def _validate_semantic_match(comparator: Mapping[str, Any]) -> bool:
    """Validate the optional, annotation-driven enum lexical rubric."""

    rubric = comparator.get("semantic_match")
    if rubric is None:
        return True
    if not isinstance(rubric, Mapping) or set(rubric) - {"all_of", "none_of"}:
        return False
    groups = rubric.get("all_of")
    forbidden = rubric.get("none_of", [])
    return (
        isinstance(groups, list)
        and bool(groups)
        and all(
            isinstance(group, list)
            and bool(group)
            and all(_is_normalizable_phrase(phrase) for phrase in group)
            for group in groups
        )
        and isinstance(forbidden, list)
        and all(_is_normalizable_phrase(phrase) for phrase in forbidden)
    )


def _validate_comparator(slot: Any) -> list[ValidationIssue]:
    comparator = slot.value.comparator
    value_type = slot.value.type
    if value_type == "free_text":
        if not slot.value.required_facts:
            return [_issue("comparator.required_facts_missing", "Free-text slots require machine-readable facts.", slot_id=slot.slot_id)]
        if not all(_is_nonblank_string(fact) for fact in slot.value.required_facts):
            return [_issue("comparator.required_facts_invalid", "Free-text facts must be nonblank strings.", slot_id=slot.slot_id)]
        return []
    if value_type == "string":
        rules = STRING_COMPARATOR_KEYS.intersection(comparator)
        if not rules:
            return [_issue("comparator.type_specific_rule_missing", "Comparator lacks a rule for the slot value type.", slot_id=slot.slot_id)]
        for rule in rules:
            value = comparator[rule]
            if not _is_nonblank_string(value):
                return [_issue("comparator.string_rule_invalid", "String comparator rules must be nonblank strings.", slot_id=slot.slot_id)]
            if rule == "regex":
                try:
                    re.compile(value)
                except re.error:
                    return [_issue("comparator.string_rule_invalid", "String regex rules must compile.", slot_id=slot.slot_id)]
        return []
    if value_type not in COMPARATOR_REQUIRED_KEYS:
        return [_issue("comparator.type_invalid", "Slot value type is unsupported.", slot_id=slot.slot_id)]
    required_keys = COMPARATOR_REQUIRED_KEYS[value_type]
    if not required_keys.issubset(comparator):
        return [_issue("comparator.type_specific_rule_missing", "Comparator lacks a rule for the slot value type.", slot_id=slot.slot_id)]
    if value_type == "enum" and not _is_nonblank_string(comparator["alias_normalization"]):
        return [_issue("comparator.enum_normalization_invalid", "Enum normalization must be nonblank.", slot_id=slot.slot_id)]
    if value_type == "enum" and not _validate_semantic_match(comparator):
        return [_issue(
            "comparator.enum_semantic_match_invalid",
            "Enum semantic_match requires nonempty all_of phrase groups and an optional none_of phrase list.",
            slot_id=slot.slot_id,
        )]
    if value_type == "boolean":
        tokens = comparator["accepted_tokens"]
        if not isinstance(tokens, list) or not tokens or not all(_is_nonblank_string(token) for token in tokens):
            return [_issue("comparator.boolean_tokens_invalid", "Boolean accepted tokens must be nonblank strings.", slot_id=slot.slot_id)]
    if value_type == "number":
        if not _is_nonblank_string(comparator["unit"]):
            return [_issue("comparator.number_unit_invalid", "Number units must be nonblank.", slot_id=slot.slot_id)]
        tolerances = (comparator["absolute_tolerance"], comparator["relative_tolerance"])
        if not all(_is_finite_number(value) and value >= 0 for value in tolerances):
            return [_issue("comparator.number_tolerance_invalid", "Number tolerances must be finite and nonnegative.", slot_id=slot.slot_id)]
        minimum, maximum = comparator["minimum"], comparator["maximum"]
        if not (_is_finite_number(minimum) and _is_finite_number(maximum) and minimum <= maximum):
            return [_issue("comparator.number_bounds_invalid", "Number bounds must be finite and ordered.", slot_id=slot.slot_id)]
    if value_type == "set" and type(comparator["allow_extra_elements"]) is not bool:
        return [_issue("comparator.set_rule_invalid", "Set extra-elements rule must be a boolean.", slot_id=slot.slot_id)]
    if value_type == "structured":
        required_fields = comparator["required_fields"]
        optional_fields = comparator["optional_fields"]
        valid_lists = all(isinstance(fields, list) and all(_is_nonblank_string(field) for field in fields) for fields in (required_fields, optional_fields))
        valid_schema = isinstance(comparator["fields"], Mapping) and type(comparator["additional_properties"]) is bool
        if not valid_lists or not valid_schema or set(required_fields).intersection(optional_fields):
            return [_issue("comparator.structured_rule_invalid", "Structured comparator fields must be valid and disjoint.", slot_id=slot.slot_id)]
    return []


def _validate_provenance(
    slot: Any,
    source_index: Mapping[str, Any],
    provenance_policy: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not slot.provenance:
        return [_issue("provenance.missing", "Every Requirement Unit requires source provenance.", slot_id=slot.slot_id)]
    allowed_sources = set(CLIENT_PROVENANCE_SOURCES | DELIVERY_PROVENANCE_SOURCES)
    if provenance_policy == "evaluation_criteria_grounded":
        allowed_sources.update(CRITERIA_PROVENANCE_SOURCES)
    for source in slot.provenance:
        source_type = _value(source, "source_type")
        source_id = _value(source, "source_id")
        if source_type not in allowed_sources:
            issues.append(_issue("provenance.untrusted_source", "Provenance is not allowed by this Registry's declared source policy.", slot_id=slot.slot_id, source_id=source_id))
            continue
        record = _record_for(source_index, source_id)
        if record is None:
            issues.append(_issue("provenance.source_missing", "Provenance source does not exist.", slot_id=slot.slot_id, source_id=source_id))
            continue
        if any(_value(source, field) in (None, "") for field in ("quote", "locator", "content_hash")):
            issues.append(_issue("provenance.evidence_incomplete", "Provenance requires quote, locator, and content hash.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("content_hash") != _value(source, "content_hash"):
            issues.append(_issue("provenance.hash_mismatch", "Provenance content hash does not match the source.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("locator") != _value(source, "locator"):
            issues.append(_issue("provenance.locator_mismatch", "Provenance locator does not match the source.", slot_id=slot.slot_id, source_id=source_id))
        if _value(source, "quote") not in str(record.get("content", "")):
            issues.append(_issue("provenance.quote_mismatch", "Provenance quote is absent from the source.", slot_id=slot.slot_id, source_id=source_id))
        if source_type in {"client_chat", "job_description"} and str(record.get("author", "")).casefold() != "client":
            issues.append(_issue("provenance.author_not_client", "Chat and job-description provenance must be Client-authored.", slot_id=slot.slot_id, source_id=source_id))
        if source_type == "client_attachment" and record.get("client_task_package") is not True:
            issues.append(_issue("provenance.attachment_not_client_package", "Attachment provenance must belong to the original Client task package.", slot_id=slot.slot_id, source_id=source_id))
        if source_type == "evaluation_criteria":
            if record.get("source_type") != "evaluation_criteria":
                issues.append(_issue("provenance.criteria_type_mismatch", "Criteria provenance must match an evaluation-criteria source record.", slot_id=slot.slot_id, source_id=source_id))
            if record.get("criterion_source") is not True:
                issues.append(_issue("provenance.criteria_origin_missing", "Criteria provenance must explicitly identify the source as evaluator-authored criteria.", slot_id=slot.slot_id, source_id=source_id))
    return issues


def _validate_runtime_public_sources(slot: Any, source_index: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for source in slot.runtime_public_sources:
        source_type = _value(source, "source_type")
        source_id = _value(source, "source_id")
        if source_type not in RUNTIME_PUBLIC_SOURCE_TYPES:
            issues.append(_issue("runtime.source_type_invalid", "Runtime public source type is not allowed.", slot_id=slot.slot_id, source_id=source_id))
            continue
        record = _record_for(source_index, source_id)
        if record is None:
            issues.append(_issue("runtime.source_missing", "Runtime public source does not exist.", slot_id=slot.slot_id, source_id=source_id))
            continue
        if record.get("source_type") != source_type:
            issues.append(_issue("runtime.source_type_mismatch", "Runtime source type does not match the source catalog.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("candidate_visible") is not True:
            issues.append(_issue("runtime.source_not_visible", "Runtime source was not candidate-visible.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("content_hash") != _value(source, "content_hash"):
            issues.append(_issue("runtime.hash_mismatch", "Runtime source hash does not match the source catalog.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("locator") != _value(source, "locator"):
            issues.append(_issue("runtime.locator_mismatch", "Runtime source locator does not match the source catalog.", slot_id=slot.slot_id, source_id=source_id))
        if record.get("quote") != _value(source, "quote"):
            issues.append(_issue("runtime.quote_mismatch", "Runtime source quote does not match the source catalog.", slot_id=slot.slot_id, source_id=source_id))
    return issues


def validate_registry(
    registry: Registry,
    source_index: Mapping[str, Any],
    manifest: TestManifest,
) -> list[ValidationIssue]:
    """Return all blocking registry, source, and cross-manifest issues."""
    if isinstance(registry, RequirementUnitRegistry):
        return _validate_requirement_unit_registry(registry, source_index, manifest)
    issues: list[ValidationIssue] = []
    slot_ids: set[str] = set()
    tests_by_id = {test.id: test for test in manifest.tests}
    for source_id in sorted(getattr(source_index, "duplicate_ids", set())):
        issues.append(_issue("source.duplicate_id", "Source IDs must be unique and stable.", source_id=source_id))

    for slot in registry.slots:
        if slot.slot_id in slot_ids:
            issues.append(_issue("slot.duplicate_id", "Slot IDs must be unique and stable.", slot_id=slot.slot_id))
        slot_ids.add(slot.slot_id)
        if not slot.slot_id.strip():
            issues.append(_issue("slot.id_missing", "Slot IDs must be nonempty.", slot_id=slot.slot_id))
        if not slot.name.strip():
            issues.append(_issue("slot.name_missing", "Slots require a name.", slot_id=slot.slot_id))
        if not slot.audit_question.strip():
            issues.append(_issue("slot.audit_question_missing", "Slots require an audit question.", slot_id=slot.slot_id))
        if slot.value.canonical is None:
            issues.append(_issue("slot.canonical_value_missing", "Slots require a canonical value.", slot_id=slot.slot_id))
        if not slot.prepared_answer.strip():
            issues.append(_issue("slot.prepared_answer_missing", "Slots require a prepared answer.", slot_id=slot.slot_id))
        if not slot.latent_at_start:
            issues.append(_issue(
                "slot.not_latent_at_start",
                "Clarification Registry slots must describe information that existed at intake time.",
                slot_id=slot.slot_id,
            ))
        if not slot.initially_visible and not slot.elicitable:
            issues.append(_issue(
                "slot.hidden_not_elicitable",
                "Hidden slots must be legally and practically elicitable from the Client.",
                slot_id=slot.slot_id,
            ))
        if slot.private_or_non_disclosable and slot.elicitable:
            issues.append(_issue(
                "slot.disclosure_policy_conflict",
                "A non-disclosable slot cannot also be marked elicitable.",
                slot_id=slot.slot_id,
            ))
        if slot.initially_visible and (
            slot.temporal_origin != "initially_public"
            or slot.benchmark_role != "public_slot"
        ):
            issues.append(_issue(
                "slot.public_temporal_classification_invalid",
                "Initially visible slots must be classified as initially-public public slots.",
                slot_id=slot.slot_id,
            ))
        if not slot.initially_visible and (
            slot.temporal_origin != "preexisting_private"
            or slot.benchmark_role != "hidden_slot"
        ):
            issues.append(_issue(
                "slot.hidden_temporal_classification_invalid",
                "Hidden Registry slots must be preexisting-private hidden slots.",
                slot_id=slot.slot_id,
            ))
        if slot.formation_evidence is not None:
            if not slot.formation_evidence.rationale.strip():
                issues.append(_issue(
                    "slot.formation_evidence_rationale_missing",
                    "Formation evidence requires a nonblank temporal rationale.",
                    slot_id=slot.slot_id,
                ))
            for source_id in slot.formation_evidence.source_ids:
                if _record_for(source_index, source_id) is None:
                    issues.append(_issue(
                        "slot.formation_evidence_source_missing",
                        "Formation evidence references an unknown source.",
                        slot_id=slot.slot_id,
                        source_id=source_id,
                    ))
        issues.extend(_validate_comparator(slot))
        if registry.interface_contract_policy == "required_per_executable_unit" and slot.testability == "executable":
            if not _is_nonblank_string(slot.requirement_text):
                issues.append(_issue(
                    "requirement.text_missing",
                    "Executable Requirement Units require a normalized requirement statement.",
                    slot_id=slot.slot_id,
                ))
            if slot.interface_contract is None:
                issues.append(_issue(
                    "requirement.interface_contract_missing",
                    "Executable Requirement Units require a stable behavior-facing interface contract.",
                    slot_id=slot.slot_id,
                ))
            else:
                interface = slot.interface_contract
                required_text = (
                    interface.entrypoint,
                    interface.signature,
                    interface.invocation,
                    interface.error_contract,
                )
                if not all(_is_nonblank_string(value) for value in required_text):
                    issues.append(_issue(
                        "requirement.interface_contract_incomplete",
                        "Interface contracts require nonblank entrypoint, signature, invocation, and error behavior.",
                        slot_id=slot.slot_id,
                    ))
        issues.extend(_validate_provenance(slot, source_index, registry.provenance_policy))
        issues.extend(_validate_runtime_public_sources(slot, source_index))

        canonical = slot.value.canonical
        if isinstance(canonical, str) and canonical.casefold() in slot.audit_question.casefold():
            issues.append(_issue("slot.audit_question_leaks_answer", "Audit question must not reveal the canonical answer.", slot_id=slot.slot_id))
        for quality_code in audit_question_quality_codes(slot.audit_question, canonical):
            issues.append(_issue(
                f"slot.audit_question_{quality_code}",
                "Audit questions must be open-ended and must not disclose numeric answer values.",
                slot_id=slot.slot_id,
            ))
        if slot.initially_visible and not slot.runtime_public_sources:
            issues.append(_issue("runtime.visible_slot_missing_public_sources", "Initially visible slots require runtime public sources.", slot_id=slot.slot_id))
        if not slot.initially_visible and slot.runtime_public_sources:
            issues.append(_issue("runtime.hidden_slot_has_public_sources", "Hidden slots cannot publish runtime sources.", slot_id=slot.slot_id))
        if slot.testability == "audit_only":
            if not slot.audit_only_reason:
                issues.append(_issue("slot.audit_only_reason_missing", "Audit-only slots require a reason.", slot_id=slot.slot_id))
            if slot.test_refs:
                issues.append(_issue("slot.audit_only_has_test_refs", "Audit-only slots cannot have test references.", slot_id=slot.slot_id))
        for test_id in slot.test_refs:
            test = tests_by_id.get(test_id)
            if test is None:
                issues.append(_issue("slot.test_ref_missing", "Slot test reference does not exist.", slot_id=slot.slot_id, test_id=test_id))
            elif test.primary_slot != slot.slot_id:
                issues.append(_issue("slot.test_ref_not_primary", "Slot test reference must point back to this slot.", slot_id=slot.slot_id, test_id=test_id))

    slots_by_id = {slot.slot_id: slot for slot in registry.slots}
    for slot in registry.slots:
        for related_id in slot.dependencies:
            if related_id == slot.slot_id or related_id not in slots_by_id:
                issues.append(_issue(
                    "slot.dependency_invalid",
                    "Slot dependencies must reference another slot in the same Registry.",
                    slot_id=slot.slot_id,
                ))
        for related_id in slot.conflicts_or_supersedes:
            if related_id == slot.slot_id or related_id not in slots_by_id:
                issues.append(_issue(
                    "slot.conflict_reference_invalid",
                    "Conflict/supersession links must reference another slot in the same Registry.",
                    slot_id=slot.slot_id,
                ))
    for test in manifest.tests:
        if test.category == "slot" and test.primary_slot:
            matching_slot = slots_by_id.get(test.primary_slot)
            if matching_slot and matching_slot.testability == "audit_only":
                issues.append(_issue("slot.audit_only_has_slot_test", "Audit-only slots cannot have Slot Tests.", slot_id=test.primary_slot, test_id=test.id))
            if matching_slot and test.id not in matching_slot.test_refs:
                issues.append(_issue("test.primary_slot_missing_backref", "Primary Slot Tests must be referenced by their slot.", slot_id=test.primary_slot, test_id=test.id))
    issues.extend(validate_test_manifest(manifest, registry))
    return issues


def _validate_requirement_unit_registry(
    registry: RequirementUnitRegistry,
    source_index: Mapping[str, Any],
    manifest: TestManifest,
) -> list[ValidationIssue]:
    """Validate the deliberately small annotation-facing RU contract."""

    issues: list[ValidationIssue] = []
    tests_by_id = {test.id: test for test in manifest.tests}
    seen_test_ids: set[str] = set()

    for unit in registry.requirement_units:
        ru_id = unit.ru_id
        if unit.content.casefold() in unit.audit_question.casefold():
            issues.append(_issue(
                "ru.audit_question_leaks_content",
                "Audit question must not reveal the Requirement Unit content.",
                slot_id=ru_id,
            ))
        for quality_code in audit_question_quality_codes(
            unit.audit_question, unit.content
        ):
            issues.append(_issue(
                f"ru.audit_question_{quality_code}",
                "Audit questions must be open-ended and must not disclose numeric answer values.",
                slot_id=ru_id,
            ))
        for keyword in unit.matching_keywords:
            if unit.content.casefold() in keyword.casefold():
                issues.append(_issue(
                    "ru.matching_keyword_leaks_content",
                    "Matching keywords must not contain the Requirement Unit answer.",
                    slot_id=ru_id,
                ))

        if unit.evaluation == "executable":
            for test_ref in unit.tests:
                if test_ref.test_id in seen_test_ids:
                    issues.append(_issue(
                        "ru.test_id_reused",
                        "A hidden Test ID can belong to only one Requirement Unit.",
                        slot_id=ru_id,
                        test_id=test_ref.test_id,
                    ))
                seen_test_ids.add(test_ref.test_id)
                manifest_test = tests_by_id.get(test_ref.test_id)
                if manifest_test is None:
                    issues.append(_issue(
                        "ru.test_missing_from_manifest",
                        "Requirement Unit test is missing from the evaluation manifest.",
                        slot_id=ru_id,
                        test_id=test_ref.test_id,
                    ))
                elif (
                    manifest_test.category != "slot"
                    or manifest_test.primary_slot != ru_id
                    or ru_id not in manifest_test.covers_slots
                ):
                    issues.append(_issue(
                        "ru.test_manifest_mapping_invalid",
                        "Requirement Unit tests must be primary Slot tests mapped back to the same RU ID.",
                        slot_id=ru_id,
                        test_id=test_ref.test_id,
                    ))

        for source in unit.provenance:
            record = _record_for(source_index, source.source_id)
            if record is None:
                issues.append(_issue(
                    "provenance.source_missing",
                    "Optional provenance references a source that does not exist.",
                    slot_id=ru_id,
                    source_id=source.source_id,
                ))

    for test in manifest.tests:
        if test.category != "slot" or not test.primary_slot:
            continue
        unit = next(
            (item for item in registry.requirement_units if item.ru_id == test.primary_slot),
            None,
        )
        if unit is None:
            continue
        if unit.evaluation == "audit_only":
            issues.append(_issue(
                "ru.audit_only_has_test",
                "audit_only Requirement Units cannot have scored tests.",
                slot_id=unit.ru_id,
                test_id=test.id,
            ))
        elif test.id not in {item.test_id for item in unit.tests}:
            issues.append(_issue(
                "ru.manifest_test_missing_backref",
                "Every primary RU test in the manifest must be listed by its Requirement Unit.",
                slot_id=unit.ru_id,
                test_id=test.id,
            ))

    issues.extend(validate_test_manifest(manifest, registry))
    return issues
