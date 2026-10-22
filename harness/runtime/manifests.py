"""V4 test-manifest models and deterministic validation."""

import math
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .models import Registry, RequirementUnitRegistry, StrictModel


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    blocking: bool
    message: str
    slot_id: str | None = None
    test_id: str | None = None
    source_id: str | None = None
    validator_version: str = "v4.1"


class TestSpec(StrictModel):
    id: str
    category: Literal["slot", "integration", "basic"]
    primary_slot: str | None = None
    covers_slots: list[str] = Field(default_factory=list)
    required: StrictBool


class TestManifest(StrictModel):
    schema_version: Literal[4] = 4
    basic_delivery_contract: str
    tests: list[TestSpec]


def _issue(code: str, message: str, *, slot_id: str | None = None, test_id: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, severity="error", blocking=True, message=message, slot_id=slot_id, test_id=test_id)


def load_test_manifest(path) -> TestManifest:
    """Load one YAML test manifest."""
    with path.open(encoding="utf-8") as handle:
        return TestManifest.model_validate(yaml.safe_load(handle))


def manifest_from_registry(registry: RequirementUnitRegistry) -> TestManifest:
    """Derive the internal scorer manifest from the annotation Registry.

    Requirement Unit files already name every owned hidden test.  Keeping a
    second hand-authored manifest would duplicate the same mapping and creates
    drift, so new SWECLAR-DC2 tasks derive it deterministically at load time.
    """

    tests = []
    for unit in registry.requirement_units:
        for test in unit.tests:
            tests.append(
                TestSpec(
                    id=test.test_id,
                    category="slot",
                    primary_slot=unit.ru_id,
                    covers_slots=[unit.ru_id],
                    required=True,
                )
            )
    return TestManifest(
        basic_delivery_contract="All executable Requirement Units must pass.",
        tests=tests,
    )





def validate_test_manifest(manifest: TestManifest, registry: Registry) -> list[ValidationIssue]:
    """Validate attribution and category rules against a slot registry."""
    issues: list[ValidationIssue] = []
    slot_ids = {slot.slot_id for slot in registry.slots}
    seen_ids: set[str] = set()
    primary_coverage: set[str] = set()

    for test in manifest.tests:
        if not test.id.strip():
            issues.append(_issue("test.id_missing", "Test IDs must be nonempty.", test_id=test.id))
        if test.id in seen_ids:
            issues.append(_issue("test.duplicate_id", "Test IDs must be unique.", test_id=test.id))
        seen_ids.add(test.id)


        unknown_slots = set(test.covers_slots) - slot_ids
        for slot_id in sorted(unknown_slots):
            issues.append(_issue("test.unknown_slot", "Test covers an unknown slot.", slot_id=slot_id, test_id=test.id))

        if test.category == "slot":
            if not test.primary_slot:
                issues.append(_issue("test.primary_slot_missing", "Slot tests require one primary slot.", test_id=test.id))
            elif test.primary_slot not in slot_ids:
                issues.append(_issue("test.primary_slot_unknown", "Primary slot must exist.", slot_id=test.primary_slot, test_id=test.id))
            elif test.primary_slot not in test.covers_slots:
                issues.append(_issue("test.primary_slot_not_covered", "Primary slot must be covered.", slot_id=test.primary_slot, test_id=test.id))
            elif test.required:
                primary_coverage.add(test.primary_slot)
        elif test.category == "integration":
            if test.primary_slot is not None:
                issues.append(_issue("test.integration_primary_slot", "Integration tests cannot have a primary slot.", test_id=test.id))
            if not test.covers_slots:
                issues.append(_issue("test.integration_missing_covers", "Integration tests must cover a slot.", test_id=test.id))
        else:
            if test.primary_slot is not None:
                issues.append(_issue("test.basic_primary_slot", "Basic tests cannot have a primary slot.", test_id=test.id))
            if test.covers_slots:
                issues.append(_issue("test.basic_covers_slots", "Basic tests cannot cover slots.", test_id=test.id))

    for slot in registry.slots:
        if slot.testability == "executable" and slot.slot_id not in primary_coverage:
            issues.append(_issue("slot.primary_test_missing", "Executable slots require a required primary Slot Test.", slot_id=slot.slot_id))

    return issues
