"""Build the Coding Agent's initial input from an explicit allowlist.

Raw Criteria remain evaluator-owned. Each Requirement Unit selected as
initially visible is disclosed through its normalized content and agreed test
interface; hidden Requirement Units remain absent until Clarify or Oracle.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field
import yaml

from .layout import input_path, workspace_path, attachment_root
from .client import render_requirement_disclosure
from .models import Registry, StrictModel


PROMPT_PATH_LIMIT = 20


class InitialTaskInput(StrictModel):
    public_task: str
    job_description: str
    source_job_description: str
    disclosure_design: str
    visible_requirement_unit_ids: list[str]
    attachment_paths: list[str]
    starter_code_paths: list[str]
    public_test_paths: list[str] = Field(default_factory=list)
    source_catalog: list[dict[str, Any]] = Field(default_factory=list)


def build_initial_task_input(
    task_dir: Path | str,
    registry: Registry,
    *,
    public_task_fallback: str | None = None,
) -> InitialTaskInput:
    """Build a deterministic prompt from raw materials and public interfaces.

    ``task_dir`` is the directory containing ``requirement_units.yaml``.  The
    preferred source layout is ``task_dir/raw``; ``task_dir.parent/raw`` is also
    accepted so the helper can read the annotation guide's task-root layout.
    Controlled tasks may provide only their explicit initial request.
    ``public_task_fallback`` is used only when no raw Job Description exists.
    """

    bundle = Path(task_dir)
    from .delivery_contract import load_delivery_contract
    load_delivery_contract(bundle, registry)
    raw_dir = _raw_directory(bundle)
    descriptions = _safe_files(raw_dir, "job_description.*") if raw_dir else []
    description_parts = [
        path.read_text(encoding="utf-8").strip()
        for path in descriptions
        if path.stat().st_size <= 2_000_000
    ]
    source_job_description = "\n\n".join(part for part in description_parts if part)
    if not source_job_description:
        source_job_description = (public_task_fallback or "").strip()
    all_attachments = _descendant_files(attachment_root(bundle))
    all_starter_code = _descendant_files(workspace_path(bundle))
    disclosure_design = getattr(registry, "disclosure_design", "source_faithful")
    benchmark_input = _benchmark_input(
        bundle,
        disclosure_design,
        attachment_names=[
            path.relative_to(attachment_root(bundle)).as_posix()
            for path in all_attachments
        ]
        if raw_dir
        else [],
    )
    job_description = source_job_description
    prompt_sources = descriptions
    if benchmark_input is not None:
        prompt_path = _bundle_file(
            bundle,
            benchmark_input.get("initial_request_file"),
            field="initial_request_file",
        )
        job_description = prompt_path.read_text(encoding="utf-8").strip()
        if not job_description:
            raise ValueError(f"{prompt_path}: controlled initial request is empty")
        prompt_sources = [prompt_path]
        if not source_job_description:
            source_job_description = job_description
    elif not source_job_description:
        raise ValueError(f"{bundle}: no raw/job_description.* source is available")

    # Published attachments are fixed across disclosure modes. Independently
    # reconstructed datasets contain synthetic materials, not customer files.
    attachments = all_attachments
    starter_code = _selected_materials(
        all_starter_code,
        workspace_path(bundle),
        benchmark_input,
        "starter_code",
    )
    # Elicitation pilot: existing code is visible, acceptance scripts and
    # requirement/interface documents are not initial candidate material.
    public_tests = []
    visible_units = []

    sections = ["# Job Description", job_description]
    if attachments:
        sections.extend(
            [
                "",
                "# Available attachments",
                *_prompt_path_listing(
                    [(Path("task_attachments") / path.relative_to(attachment_root(bundle))).as_posix() for path in attachments]
                ),
            ]
        )
    if starter_code:
        sections.extend(
            [
                "",
                "# Starter code workspace (repository-relative paths)",
                *_prompt_path_listing(
                    [path.relative_to(workspace_path(bundle)).as_posix() for path in starter_code]
                ),
            ]
        )
    if public_tests:
        sections.extend([
            "", "# Public tests (prepared outside the source workspace)",
            *_prompt_path_listing([
                "/public_tests/" + path.relative_to(bundle / "public_tests").as_posix()
                for path in public_tests
            ]),
            "The benchmark prepares dependencies before your work begins. "
            "Use the starter instructions to run these public checks.",
        ])
    if visible_units:
        sections.extend(
            [
                "",
                "# Initially disclosed requirements",
                (
                    "The following requirements are visible at task start. "
                    "Each disclosure contains the required behavior and, when "
                    "applicable, the agreed delivery interface. Private tests, "
                    "assertions, and test data are not provided."
                ),
            ]
        )
        for unit in visible_units:
            sections.extend(
                [
                    "",
                    f"## {unit.name}",
                    render_requirement_disclosure(unit),
                ]
            )
    from .public_sources import public_source_roots
    environment_sources = []  # Infrastructure source is not task starter code.
    if environment_sources:
        sections.extend([
            '', '# Read-only public environment source',
            'These frozen provider/scaffolding files are public inputs, not hidden acceptance tests. '
            'Use read to follow relevant imports. They must not be edited.',
            *_prompt_path_listing([item['virtual'] for item in environment_sources]),
        ])
    public_task = "\n".join(sections).strip()

    source_catalog = [
        {
            "source_type": "task_prompt",
            "source_id": "initial-task",
            "candidate_visible": True,
            "path": _relative_path(path, bundle),
        }
        for path in prompt_sources
    ]
    return InitialTaskInput(
        public_task=public_task,
        job_description=job_description,
        source_job_description=source_job_description,
        disclosure_design=disclosure_design,
        visible_requirement_unit_ids=[unit.slot_id for unit in visible_units],
        attachment_paths=[(Path("task_attachments") / path.relative_to(attachment_root(bundle))).as_posix() for path in attachments],
        starter_code_paths=[_relative_path(path, bundle) for path in starter_code],
        public_test_paths=[_relative_path(path, bundle) for path in public_tests],
        source_catalog=source_catalog,
    )


def _benchmark_input(
    bundle: Path,
    disclosure_design: str,
    *,
    attachment_names: list[str],
) -> dict[str, Any] | None:
    """Load the controlled prompt and optional starter-code selection.

    Original attachments are never a disclosure-control surface.  A bundle
    that attempts to subset them is rejected instead of silently producing a
    different task for different experiment modes.
    """

    path = input_path(bundle)
    if not path.is_file():
        if disclosure_design == "controlled_requirement_disclosure":
            raise ValueError(
                f"{bundle}: controlled disclosure requires benchmark_input.yaml"
            )
        return None
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"{path}: invalid YAML: {error}") from error
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: expected a YAML mapping")
    if "schema_version" in document and document.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    document = dict(document)
    input_design = document.get("design")
    if input_design == "reconstructed_interface":
        # Pre-release bundles used this name for the same controlled
        # disclosure policy. Keep them readable while exposing one canonical
        # platform value.
        input_design = "controlled_requirement_disclosure"
        document["design"] = input_design
    if input_design is not None and input_design != disclosure_design:
        raise ValueError(
            f"{path}: design must match Registry disclosure_design"
        )
    materials = document.get("materials")
    if not isinstance(materials, Mapping) and "initial_request" in document:
        # Compatibility for the earliest compact annotation bundle. It does
        # not add a second public format; the reader normalizes it in memory.
        document["initial_request_file"] = document.get("initial_request")
        materials = {
            "attachments": document.get("initial_attachments", "all"),
            "starter_code": (
                [] if document.get("starter_code") is None else document.get("starter_code")
            ),
        }
        document["materials"] = materials
    if not isinstance(materials, Mapping):
        raise ValueError(f"{path}: materials must be a mapping")
    attachment_selection = materials.get("attachments", "all")
    if isinstance(attachment_selection, list):
        normalized_attachments = []
        for name in attachment_selection:
            if not isinstance(name, str):
                break
            prefix = "raw/attachments/"
            normalized_attachments.append(
                name[len(prefix) :] if name.startswith(prefix) else name
            )
        if (
            len(normalized_attachments) == len(attachment_selection)
            and len(set(normalized_attachments)) == len(normalized_attachments)
            and set(normalized_attachments) == set(attachment_names)
        ):
            # An explicit list containing every source attachment is
            # semantically identical to ``all``.
            materials = dict(materials)
            materials["attachments"] = "all"
            document["materials"] = materials
            attachment_selection = "all"
    if attachment_selection == [] and not attachment_names:
        # Older bundles used an empty list to say that the source Job had no
        # attachments.  This is equivalent to exposing all zero attachments
        # and does not create a disclosure-control surface.
        materials = dict(materials)
        materials["attachments"] = "all"
        document["materials"] = materials
    elif attachment_selection != "all":
        raise ValueError(
            f"{path}: materials.attachments must be 'all'; original Job "
            "attachments cannot be hidden"
        )
    return dict(document)


def _bundle_file(bundle: Path, value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{bundle / 'benchmark_input.yaml'}: {field} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{bundle / 'benchmark_input.yaml'}: unsafe {field}")
    candidate = (bundle / relative).resolve()
    try:
        candidate.relative_to(bundle.resolve())
    except ValueError as error:
        raise ValueError(f"{candidate}: controlled input is outside the task bundle") from error
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"{candidate}: controlled input file does not exist")
    return candidate


def _selected_materials(
    available: list[Path],
    root: Path | None,
    benchmark_input: dict[str, Any] | None,
    field: str,
) -> list[Path]:
    if benchmark_input is None:
        return available
    selection = benchmark_input["materials"].get(field)
    if selection == "all":
        return available
    if not isinstance(selection, list) or any(
        not isinstance(item, str) for item in selection
    ):
        raise ValueError(
            f"benchmark_input.yaml: materials.{field} must be 'all' or a path list"
        )
    if root is None:
        if selection:
            raise ValueError(f"benchmark_input.yaml: no raw {field} directory exists")
        return []
    by_name = {path.relative_to(root).as_posix(): path for path in available}
    normalized_selection = []
    prefix = f"raw/{field}/"
    for name in selection:
        normalized_selection.append(name[len(prefix) :] if name.startswith(prefix) else name)
    unknown = sorted(set(normalized_selection) - set(by_name))
    if unknown:
        raise ValueError(
            f"benchmark_input.yaml: unknown materials.{field}: {unknown}"
        )
    return [by_name[name] for name in normalized_selection]


def _raw_directory(bundle: Path) -> Path | None:
    for candidate in (bundle / "raw", bundle.parent / "raw"):
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    return None


def _safe_files(root: Path | None, pattern: str) -> list[Path]:
    if root is None:
        return []
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    )


def _descendant_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _relative_path(path: Path, bundle: Path) -> str:
    for root in (bundle, bundle.parent):
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    raise ValueError(f"{path}: allowlisted path is outside the task directory")


def _agent_attachment_path(path: Path, raw_dir: Path | None) -> str:
    """Return the stable path mounted into the Coding Agent workspace."""

    if raw_dir is None:
        raise ValueError("attachment path requires a raw task directory")
    return (Path("task_attachments") / path.relative_to(attachment_root(bundle))).as_posix()


def _agent_starter_path(path: Path, raw_dir: Path | None) -> str:
    """Return the repository-relative path visible inside the task runtime."""

    if raw_dir is None:
        raise ValueError("starter path requires a raw task directory")
    return path.relative_to(raw_dir / "starter_code").as_posix()


def _prompt_path_listing(paths: list[str]) -> list[str]:
    """Keep prompt context bounded while retaining the complete machine list."""

    visible = paths[:PROMPT_PATH_LIMIT]
    lines = [f"- {path}" for path in visible]
    remaining = len(paths) - len(visible)
    if remaining:
        lines.append(f"- ... {remaining} additional files available in the workspace")
    return lines
