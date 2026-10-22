"""Digest-pinned, per-run Docker runtimes for official benchmark tasks.

The official task image is treated as the immutable source of the repository.
Candidate code lives only in a session container while the run is active.  A
binary ``base..HEAD`` patch and a source-only ``git archive`` are exported to
the persistent host workdir after each persisted Coding checkpoint. If the container is lost,
``prepare`` recreates it from the pinned image and reapplies that patch.

Hidden verifier assets are deliberately absent from ``prepare`` and
``execute``.  They are copied into the container only by ``run_verifier`` after
the Candidate has finished.
"""

from __future__ import annotations

from .layout import workspace_path
from .container_cleanup import BoundedRemoval

import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping

import yaml
from pydantic import Field, field_validator, model_validator

from .artifacts import ArtifactStore
from .canonical import digest_json
from .models import StrictModel


_DIGEST_IMAGE_RE = re.compile(
    r"(?P<repository>[a-z0-9][a-z0-9._:/-]*)@"
    r"(?P<digest>sha256:[0-9a-f]{64})\Z"
)
_TAGGED_IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._:/-]*:[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}\Z")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_MEMORY_RE = re.compile(r"[1-9][0-9]*(?:[kKmMgG](?:[bB])?)?\Z")
_CONTAINER_COMPONENT_RE = re.compile(r"[^a-z0-9_.-]+")
_MAX_ARCHIVE_MEMBERS = 200_000
_MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
_MAX_VERIFIER_BYTES = 128 * 1024 * 1024
_VENDOR_PARTS = (
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".cache",
    ".npm",
    ".pytest_cache",
    "__pycache__",
)
_SOURCE_PATHSPEC = [
    ".",
    *[f":(exclude,glob)**/{part}/**" for part in _VENDOR_PARTS],
    ":(exclude,glob)task_attachments/**",
]


class TaskRuntimeError(RuntimeError):
    """The isolated task runtime could not complete an operation."""


class TaskRuntimeConfigError(TaskRuntimeError, ValueError):
    """``runtime.yaml`` is missing, unsafe, or internally inconsistent."""


def _docker_bytes(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([kmgb]*)", value.lower())
    if match is None:
        raise ValueError("invalid Docker byte quantity")
    units = {"": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2,
             "g": 1024**3, "gb": 1024**3}
    return int(match.group(1)) * units[match.group(2)]


class RuntimeResources(StrictModel):
    cpus: float = Field(default=4, gt=0, le=64)
    memory: str = "4g"
    pids_limit: int = Field(default=512, ge=32, le=16_384)
    shm_size: str = "256m"
    workspace_size: str | None = None
    temporary_size: str = "1g"
    verifier_size: str = "128m"
    workspace_executable: bool = False

    @field_validator("workspace_size", "temporary_size", "verifier_size")
    @classmethod
    def storage_is_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if _MEMORY_RE.fullmatch(value) is None or not 64 * 1024**2 <= _docker_bytes(value) <= 64 * 1024**3:
            raise ValueError("storage must be a Docker byte quantity between 64m and 64g")
        return value.lower()

    @field_validator("memory", "shm_size")
    @classmethod
    def memory_is_a_bounded_docker_quantity(cls, value: str) -> str:
        if not isinstance(value, str) or _MEMORY_RE.fullmatch(value) is None:
            raise ValueError("memory must be a positive Docker byte quantity")
        normalized = value.lower()
        units = {"k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3}
        match = re.fullmatch(r"([1-9][0-9]*)([a-z]*)", normalized)
        assert match is not None
        size = int(match.group(1)) * units.get(match.group(2), 1)
        if not 256 * 1024**2 <= size <= 64 * 1024**3:
            raise ValueError("memory must be between 256m and 64g")
        return normalized


class RuntimeTimeouts(StrictModel):
    prepare: int = Field(default=600, ge=1, le=3_600)
    command: int = Field(default=120, ge=1, le=3_600)
    export: int = Field(default=180, ge=1, le=3_600)
    verifier: int = Field(default=120, ge=1, le=3_600)


class RuntimeGateMapping(StrictModel):
    all_of: list[str] = Field(min_length=1)

    @field_validator("all_of")
    @classmethod
    def gate_ids_are_unique_and_nonempty(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for gate_id in value:
            if not isinstance(gate_id, str) or not gate_id.strip():
                raise ValueError("official gate IDs must be nonempty strings")
            if gate_id in normalized:
                raise ValueError("official gate IDs must be unique per V4 test")
            normalized.append(gate_id)
        return normalized


class RuntimeVerifier(StrictModel):
    host_tests_path: str
    container_path: str
    command: str
    reward_path: str
    gates_path: str
    expected_gate_ids: list[str] = Field(min_length=1)
    gate_mapping: dict[str, RuntimeGateMapping] = Field(min_length=1)

    @field_validator("host_tests_path")
    @classmethod
    def host_tests_path_is_relative_and_normalized(cls, value: str) -> str:
        return _safe_relative_posix_path(value, field="host_tests_path")

    @field_validator("container_path", "reward_path", "gates_path")
    @classmethod
    def container_paths_are_absolute_and_normalized(cls, value: str) -> str:
        return _safe_absolute_posix_path(value, field="container verifier path")

    @field_validator("command")
    @classmethod
    def command_is_nonempty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("verifier command must be a nonempty string")
        return value

    @field_validator("expected_gate_ids")
    @classmethod
    def expected_gate_ids_are_unique_and_nonempty(
        cls, value: list[str]
    ) -> list[str]:
        seen: set[str] = set()
        for gate_id in value:
            if (
                not isinstance(gate_id, str)
                or not gate_id
                or gate_id != gate_id.strip()
            ):
                raise ValueError(
                    "expected official gate IDs must be nonempty normalized strings"
                )
            if gate_id in seen:
                raise ValueError("expected official gate IDs must be unique")
            seen.add(gate_id)
        return value

    @field_validator("gate_mapping")
    @classmethod
    def v4_test_ids_are_nonempty(cls, value: dict[str, RuntimeGateMapping]):
        if any(not isinstance(test_id, str) or not test_id.strip() for test_id in value):
            raise ValueError("V4 test IDs must be nonempty strings")
        return value

    @model_validator(mode="after")
    def verifier_directory_is_dedicated(self) -> "RuntimeVerifier":
        root = PurePosixPath(self.container_path)
        if root != PurePosixPath("/private/tests") and not str(root).startswith("/tmp/sweclar-"):
            raise ValueError("container_path must be /private/tests or a dedicated /tmp/sweclar-* directory")
        expected = set(self.expected_gate_ids)
        referenced = {
            gate_id
            for rule in self.gate_mapping.values()
            for gate_id in rule.all_of
        }
        unknown = sorted(referenced - expected)
        if unknown:
            raise ValueError(
                "gate_mapping references gates absent from expected_gate_ids: "
                + ", ".join(unknown)
            )
        return self


class TaskRuntimeSpec(StrictModel):
    schema_version: Literal[1] = 1
    image_ref: str
    source_image_tag: str
    platform: str | None = Field(default=None, pattern=r"^linux/(amd64|arm64)$")
    workspace_path: str
    base_commit: str
    candidate_uid: int | None = Field(default=None, ge=1, le=65535)
    preflight_command: str | None = None
    phase_sealed_support: bool = False
    public_materials_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    network: Literal["none"] = "none"
    resources: RuntimeResources = Field(default_factory=RuntimeResources)
    timeouts: RuntimeTimeouts = Field(default_factory=RuntimeTimeouts)
    verifier: RuntimeVerifier
    # Set by ``load_task_runtime`` only.  On-disk declarations are rejected.
    bundle_dir: Path | None = Field(default=None, exclude=True, repr=False)

    @field_validator("image_ref")
    @classmethod
    def image_is_digest_pinned(cls, value: str) -> str:
        if not isinstance(value, str) or _DIGEST_IMAGE_RE.fullmatch(value) is None:
            raise ValueError("image_ref must be an OCI image pinned with @sha256:<64 hex>")
        return value

    @field_validator("source_image_tag")
    @classmethod
    def source_tag_is_a_tag_not_a_digest(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or "@" in value
            or _TAGGED_IMAGE_RE.fullmatch(value) is None
        ):
            raise ValueError("source_image_tag must be a tagged OCI image reference")
        return value

    @field_validator("preflight_command")
    @classmethod
    def preflight_is_nonempty(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("preflight_command must be a nonempty command")
        return value

    @field_validator("workspace_path")
    @classmethod
    def workspace_is_absolute_and_normalized(cls, value: str) -> str:
        normalized = _safe_absolute_posix_path(value, field="workspace_path")
        if normalized == "/":
            raise ValueError("workspace_path cannot be the container root")
        return normalized

    @field_validator("base_commit")
    @classmethod
    def base_commit_is_hex(cls, value: str) -> str:
        if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
            raise ValueError("base_commit must contain 7-40 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def verifier_is_outside_candidate_workspace(self) -> "TaskRuntimeSpec":
        if self.candidate_uid is not None and self.preflight_command is None:
            raise ValueError("restricted candidate runtimes require independent preflight")
        if self.phase_sealed_support and (self.candidate_uid is None or self.resources.workspace_size is None):
            raise ValueError("phase-sealed support requires a bounded restricted runtime")
        image_repository = self.image_ref.rsplit("@", 1)[0]
        tag_repository = self.source_image_tag.rsplit(":", 1)[0]
        if tag_repository != image_repository:
            raise ValueError("source_image_tag and image_ref must name the same repository")
        workspace = PurePosixPath(self.workspace_path)
        if self.resources.workspace_size is not None:
            if self.candidate_uid is None or not workspace.is_relative_to("/workspace"):
                raise ValueError("bounded runtimes require a restricted candidate and a /workspace path")
            if not all(PurePosixPath(p).is_relative_to("/private") for p in (
                self.verifier.container_path, self.verifier.reward_path, self.verifier.gates_path
            )):
                raise ValueError("bounded runtimes require verifier assets and results under /private")
        for field_name, value in (
            ("container_path", self.verifier.container_path),
            ("reward_path", self.verifier.reward_path),
            ("gates_path", self.verifier.gates_path),
        ):
            try:
                PurePosixPath(value).relative_to(workspace)
            except ValueError:
                continue
            raise ValueError(f"verifier {field_name} cannot be inside workspace_path")
        return self

    def provenance(self) -> dict[str, Any]:
        """Return a key-free, JSON-safe runtime snapshot for persisted runs."""

        snapshot = self.model_dump(mode="json", exclude={"bundle_dir"})
        verifier_digest = self.verifier_digest()
        if verifier_digest is not None:
            snapshot["verifier_digest"] = verifier_digest
        return snapshot

    def verifier_digest(self) -> str | None:
        """Digest the complete hidden evaluator contract and its file bytes.

        The runtime image digest only freezes the starting repository.  Hidden
        tests are mounted later from the task bundle, so their own digest must
        be persisted separately for an evaluation result to be reproducible.
        """

        if self.bundle_dir is None:
            return None
        root = (self.bundle_dir / self.verifier.host_tests_path).resolve()
        try:
            root.relative_to(self.bundle_dir)
        except ValueError:
            raise TaskRuntimeConfigError(
                "verifier host path escapes the V4 bundle"
            ) from None
        _validate_verifier_tree(root)
        files = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            value = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": len(value),
                    "digest": "sha256:" + hashlib.sha256(value).hexdigest(),
                }
            )
        return digest_json(
            {
                "schema_version": 1,
                "verifier": self.verifier.model_dump(mode="json"),
                "files": files,
            }
        )


def load_task_runtime(
    bundle_dir: Path | str, *, catalogs: dict | None = None
) -> TaskRuntimeSpec | None:
    """Load a task runtime from its explicit definition or central Runtime Catalog.

    Runtime/image details are platform configuration, not annotation data.
    Task folders may reference the single catalog at
    ``agent_benchmark/runtime_catalog.yaml`` by their directory task ID.
    Callers may share parsed catalogs within one operation; never retain them
    across operations, so later reads observe configuration updates.
    """

    bundle = Path(bundle_dir)
    path = bundle / "runtime.yaml"
    if path.is_file():
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise TaskRuntimeConfigError(f"{path}: invalid runtime YAML: {error}") from error
    else:
        task_id = bundle.name
        configured_catalog = os.environ.get("SWECLAR_RUNTIME_CATALOG")
        catalog_path = Path(configured_catalog).resolve() if configured_catalog else bundle.parent.parent / "runtime_catalog.yaml"
        if not catalog_path.is_file():
            return None
        try:
            if catalogs is None:
                catalogs = {}
            if catalog_path not in catalogs:
                catalogs[catalog_path] = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
            catalog = catalogs[catalog_path]
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise TaskRuntimeConfigError(
                f"{catalog_path}: invalid runtime catalog YAML: {error}"
            ) from error
        entries = catalog.get("tasks") if isinstance(catalog, Mapping) else None
        document = entries.get(task_id) if isinstance(entries, Mapping) else None
        if document is None:
            return None
        path = catalog_path
    if not isinstance(document, Mapping):
        raise TaskRuntimeConfigError(f"{path}: expected a YAML mapping")
    if "bundle_dir" in document:
        raise TaskRuntimeConfigError(f"{path}: bundle_dir is controlled by the loader")
    try:
        spec = TaskRuntimeSpec.model_validate(document)
    except Exception as error:
        raise TaskRuntimeConfigError(f"{path}: invalid task runtime: {error}") from error

    resolved_bundle = bundle.resolve()
    if spec.public_materials_digest is not None and spec.public_materials_digest != task_public_material_digest(resolved_bundle):
        raise TaskRuntimeConfigError("public materials changed; rebuild the prepared task runtime")
    tests_path = (resolved_bundle / spec.verifier.host_tests_path).resolve()
    try:
        tests_path.relative_to(resolved_bundle)
    except ValueError:
        raise TaskRuntimeConfigError(
            f"{path}: verifier host_tests_path escapes the V4 bundle"
        ) from None
    return spec.model_copy(update={"bundle_dir": resolved_bundle})


def task_public_material_digest(bundle: Path) -> str:
    """Bind the prepared image to its published starter and public test bytes."""
    files = {}
    for directory in (workspace_path(bundle), bundle / "public_tests"):
        if directory.is_symlink():
            raise TaskRuntimeConfigError("public material directories cannot be symlinks")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise TaskRuntimeConfigError("public materials cannot contain symlinks")
            if path.is_file():
                files[path.relative_to(bundle).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


class OfficialTaskRuntime:
    """Operate one digest-pinned official task image per benchmark session."""

    def __init__(self, spec: TaskRuntimeSpec, tool_env: Mapping[str, str]) -> None:
        self.spec = spec
        self.tool_env = _validated_tool_env(tool_env)
        # The managed container/workdir fingerprint freezes only the candidate
        # starting runtime. Hidden verifier assets are injected after coding
        # and may receive a separately versioned correction; changing them
        # must not make an otherwise identical saved Candidate patch unrestorable.
        canonical = json.dumps(
            self.spec.model_dump(mode="json", exclude={"bundle_dir"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._fingerprint = "sha256:" + hashlib.sha256(canonical).hexdigest()

    def prepare(self, session_id: str, host_workdir: Path | str) -> bool:
        """Create or restore a runtime and export its baseline repository.

        Returns ``True`` only when this host workdir receives its first pristine
        baseline.  A missing container with an existing patch is rebuilt from
        the pinned image and restored without exposing verifier assets.
        """

        workdir = Path(host_workdir).resolve()
        runtime_dir = workdir / "_runtime"
        deliverable = workdir / "deliverable"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        marker_path = runtime_dir / "runtime.json"
        patch_path = runtime_dir / "task.patch"
        first_baseline = not marker_path.exists()
        if not first_baseline:
            self._validate_marker(marker_path)

        name = self._container_name(session_id)
        container = self._inspect_container(name)
        if first_baseline and container is not None:
            # A host workdir without its marker must never inherit opaque state.
            if not self._is_managed_container(container):
                raise TaskRuntimeError("container name is occupied by an unmanaged runtime")
            self._remove_container(name)
            container = None
        if container is not None and not self._is_expected_container(container):
            raise TaskRuntimeError("existing task container does not match the frozen runtime")

        if (container is not None and self.spec.resources.workspace_size is not None
                and not bool(container.get("State", {}).get("Running"))):
            # Docker clears tmpfs on stop. Restore from the last persisted patch,
            # exactly as after container loss; never restart an empty workspace.
            self._remove_container(name)
            container = None

        created = container is None
        if created:
            self._ensure_image()
            try:
                self._create_container(name)
                if self.spec.resources.workspace_size is not None:
                    self._seed_workspace(name)
                if self.spec.phase_sealed_support:
                    self._container_shell_checked(name,
                        "cp -a /opt/sweclar/sealed_support/. /public_tests/ && chmod -R a+rX /public_tests",
                        self.spec.timeouts.prepare, "stage independent preflight support")
            except TaskRuntimeError:
                self.cleanup(session_id)
                raise
            self._verify_pristine_base(name)
            if self.spec.preflight_command is not None:
                try:
                    checked = self._checked(
                        ["docker", "exec", "--user", "0:0", "--workdir", "/", name,
                         "/bin/sh", "-c", self.spec.preflight_command],
                        self.spec.timeouts.prepare, "independent environment preflight",
                    )
                except TaskRuntimeError:
                    self.cleanup(session_id)
                    raise
                _atomic_write(runtime_dir / "preflight.json", json.dumps({
                    "image_ref": self.spec.image_ref,
                    "command": self.spec.preflight_command,
                    "returncode": checked.returncode,
                    "output": checked.stdout,
                }, ensure_ascii=False).encode("utf-8"))
            if self.spec.phase_sealed_support:
                self._container_shell_checked(name,
                    "chmod -R go-rwx /public_tests && chmod 700 /public_tests",
                    self.spec.timeouts.prepare, "seal evaluator support before candidate work")
            if patch_path.is_file() and patch_path.stat().st_size:
                self._restore_patch(name, patch_path)
        elif not bool(container.get("State", {}).get("Running")):
            self._checked(["docker", "start", name], self.spec.timeouts.prepare, "start container")

        self._verify_base_ancestry(name)
        if first_baseline or created or not deliverable.is_dir():
            self._export_archive(name, deliverable)
        self._write_marker(marker_path)
        return first_baseline

    def execute(
        self,
        session_id: str,
        command: str,
        timeout: int | None = None,
    ) -> tuple[int, str, bool]:
        """Execute one Candidate command without invoking a host shell."""
        return self._execute(session_id, command, timeout, user=self.spec.candidate_uid)

    def _execute(
        self, session_id: str, command: str, timeout: int | None, *, user: int | None,
    ) -> tuple[int, str, bool]:
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ValueError("command must be a nonempty string")
        seconds = self.spec.timeouts.command if timeout is None else timeout
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 1:
            raise ValueError("timeout must be a positive integer")
        name = self._container_name(session_id)
        self._require_running_container(name)
        env_args = [
            item
            for key, value in self.tool_env.items()
            for item in ("--env", f"{key}={value}")
        ]
        argv = [
            "docker",
            "exec",
            "--workdir",
            self.spec.workspace_path,
            *env_args,
            *(["--user", f"{user}:{user}"] if user is not None else []),
            name,
            "timeout",
            "-s",
            "KILL",
            str(seconds),
            "/bin/bash",
            # Do not use a login shell here.  Login profiles in task images may
            # replace PATH, which hides image-provided toolchains (for example
            # Foundry's /root/.foundry/bin/forge) from both Coding Agent
            # actions and the official verifier.  The image's declared ENV is
            # the reproducible runtime contract; a non-login shell preserves it.
            "-c",
            command,
        ]
        try:
            completed = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=seconds + 15,
            )
        except subprocess.TimeoutExpired as error:
            output = _timeout_output(error)
            return 124, output, True
        output = completed.stdout or ""
        if completed.returncode in {124, 137}:
            return 124, output, True
        return completed.returncode, output, False

    def stage_public_attachments(
        self,
        session_id: str,
        attachments: Mapping[str, Path | str],
    ) -> None:
        """Copy candidate-visible attachments into the managed workspace.

        The files come from the frozen task bundle and are deliberately kept
        outside the Candidate patch/archive through ``_SOURCE_PATHSPEC``.  This
        gives Pi's native ``read`` tool the same stable relative paths shown in
        the task prompt without exposing evaluator-owned Criteria or tests.
        """

        name = self._container_name(session_id)
        self._require_running_container(name)
        workspace = PurePosixPath(self.spec.workspace_path)
        for agent_path, source_value in sorted(attachments.items()):
            relative = PurePosixPath(agent_path)
            if (
                relative.is_absolute()
                or not relative.parts
                or relative.parts[0] != "task_attachments"
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise TaskRuntimeError(
                    f"invalid candidate attachment path: {agent_path}"
                )
            source = Path(source_value).resolve()
            if not source.is_file() or source.is_symlink():
                raise TaskRuntimeError(
                    f"candidate attachment is missing or unsafe: {agent_path}"
                )
            destination = workspace.joinpath(relative)
            self._checked(
                ["docker", "exec", name, "mkdir", "-p", str(destination.parent)],
                self.spec.timeouts.prepare,
                "create candidate attachment directory",
            )
            self._copy_into_container(name, source, str(destination), "stage candidate attachment")

    def snapshot_and_export(
        self,
        session_id: str,
        host_workdir: Path | str,
    ) -> dict[str, Any] | None:
        """Commit Candidate changes, persist a binary patch, and export sources."""

        workdir = Path(host_workdir).resolve()
        self.prepare(session_id, workdir)
        name = self._container_name(session_id)
        workspace = self.spec.workspace_path

        self._git_checked(
            name,
            ["add", "-A", "--", *_SOURCE_PATHSPEC],
            "stage candidate changes",
        )
        staged = self._git_result(
            name,
            ["diff", "--cached", "--quiet", "--", *_SOURCE_PATHSPEC],
        )
        if staged.returncode not in {0, 1}:
            raise TaskRuntimeError("cannot inspect staged candidate changes")
        if staged.returncode == 1:
            self._git_checked(
                name,
                [
                    "-c",
                    "user.name=SWE-Clar",
                    "-c",
                    "user.email=benchmark@local",
                    "commit",
                    "-m",
                    "sweclar: snapshot candidate action",
                ],
                "commit candidate changes",
            )

        self._verify_base_ancestry(name)
        head = self._git_text(name, ["rev-parse", "HEAD"], "read candidate HEAD").strip()
        patch = self._git_bytes(
            name,
            [
                "diff",
                "--binary",
                "--full-index",
                f"{self.spec.base_commit}..HEAD",
                "--",
                *_SOURCE_PATHSPEC,
            ],
            "create binary task patch",
        )
        patch_path = workdir / "_runtime" / "task.patch"
        if patch:
            # Persist recovery state before refreshing the human-facing export.
            # A restart can therefore never leave a newer export with an older
            # reconstruction patch.
            _atomic_write(patch_path, patch)
        else:
            patch_path.unlink(missing_ok=True)
        self._export_archive(name, workdir / "deliverable")
        self._write_marker(workdir / "_runtime" / "runtime.json")

        if not patch:
            return None
        diff_stat = self._git_text(
            name,
            [
                "diff",
                "--stat",
                f"{self.spec.base_commit}..HEAD",
                "--",
                *_SOURCE_PATHSPEC,
            ],
            "summarize candidate diff",
        ).strip()
        names = self._git_bytes(
            name,
            [
                "diff",
                "--name-only",
                "-z",
                f"{self.spec.base_commit}..HEAD",
                "--",
                *_SOURCE_PATHSPEC,
            ],
            "list candidate files",
        )
        files_changed = [
            value.decode("utf-8", errors="replace")
            for value in names.split(b"\x00")
            if value
        ]
        return {
            "commit": head,
            "base_commit": self.spec.base_commit,
            "files_changed": files_changed,
            "diff_stat": diff_stat,
            "patch_path": "_runtime/task.patch",
            "patch_sha256": "sha256:" + hashlib.sha256(patch).hexdigest(),
        }

    def _reset_verifier_runtime(self, session_id: str, workdir: Path) -> None:
        self._remove_container(self._container_name(session_id))
        self.prepare(session_id, workdir)

    def run_verifier(self, session_id, host_workdir, tests_dir):
                # Preserve the pinned _run_verifier and gate mapping verbatim.
                # Its removal and this finalizer share an idempotent ID-aware helper.
                workdir = Path(host_workdir).resolve()
                evidence = dict(schema_version=1, kind='official_verifier_evidence',
                                attempt_id=uuid.uuid4().hex, session_id=session_id,
                                runtime_provenance=self.spec.provenance(), phase='preparation',
                                ran=False, returncode=None, timed_out=False, output='',
                                reward_text=None, gates_text=None, reward=None, gates={},
                                error=None, cleanup_error=None)
                error = None
                result = None
                try:
                    result = self._run_verifier(session_id, workdir, tests_dir, evidence)
                except Exception as caught:
                    error = caught
                    if evidence['error'] is None:
                        evidence['error'] = dict(type=type(caught).__name__, message=str(caught),
                                                 phase=evidence['phase'])
                finally:
                    if self.spec.phase_sealed_support:
                        try:
                            self._remove_container(self._container_name(session_id))
                        except Exception as caught:
                            evidence['cleanup_error'] = dict(type=type(caught).__name__, message=str(caught))
                            if error is None:
                                error = caught
                evidence['phase'] = 'complete' if error is None else evidence['phase']
                reference = self._persist_verifier_evidence(workdir, evidence)
                if error is not None:
                    error.verifier_evidence = reference
                    raise error
                result['evidence'] = reference
                return result

    @staticmethod
    def _persist_verifier_evidence(workdir: Path, evidence: dict[str, Any]) -> dict[str, Any]:
        store = ArtifactStore(workdir / "_runtime" / "verifier-evidence")
        # put_json canonicalizes line endings; captured diagnostic text must
        # retain its exact spelling, including CRLF and terminal carriage returns.
        reference = store.put_bytes(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        hexadecimal = reference.digest.removeprefix("sha256:")
        return {
            "path": str(Path("_runtime/verifier-evidence/sha256") / hexadecimal[:2] / hexadecimal[2:]),
            "sha256": reference.digest,
            "size": reference.size,
            "attempt_id": evidence["attempt_id"],
        }

    def _run_verifier(
        self,
        session_id: str,
        host_workdir: Path,
        tests_dir: Path | str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:

        workdir = Path(host_workdir).resolve()
        snapshot = self.snapshot_and_export(session_id, workdir)
        name = self._container_name(session_id)
        source = self._resolve_tests_dir(tests_dir)
        _validate_verifier_tree(source)
        verifier = self.spec.verifier

        # Evaluate only the persisted Candidate patch, never the mutable
        # container state left behind by the Coding Agent.  Recreating from the
        # digest-pinned image restores image-provided dependencies and removes
        # untracked processes/files while ``prepare`` reapplies the exact
        # source patch captured above.
        self._reset_verifier_runtime(session_id, workdir)
        if self.spec.phase_sealed_support:
            # The old coding container was destroyed above. Only transport and
            # fixture files become readable in this disposable scoring runtime;
            # assertion suites and private expected outputs stay root-only.
            self._container_shell_checked(name,
                "python -I /opt/sweclar/open_scoring_support.py",
                self.spec.timeouts.prepare, "stage scoring-only transports")
        saved_head = self._git_text(name, ["rev-parse", "HEAD"], "read pre-verifier HEAD").strip()

        self._container_shell_checked(
            name,
            f"rm -rf -- {_shell_quote(verifier.container_path)} && "
            f"mkdir -p -- {_shell_quote(verifier.container_path)} "
            f"{_shell_quote(str(PurePosixPath(verifier.reward_path).parent))} "
            f"{_shell_quote(str(PurePosixPath(verifier.gates_path).parent))} && "
            f"rm -f -- {_shell_quote(verifier.reward_path)} "
            f"{_shell_quote(verifier.gates_path)}",
            self.spec.timeouts.export,
            "create verifier directory",
        )
        self._copy_into_container(name, source, verifier.container_path, "copy verifier assets")

        if self.spec.candidate_uid is not None:
            protected = {verifier.container_path,
                         str(PurePosixPath(verifier.reward_path).parent),
                         str(PurePosixPath(verifier.gates_path).parent)}
            self._container_shell_checked(
                name, "chmod 700 -- " + " ".join(_shell_quote(p) for p in sorted(protected)),
                self.spec.timeouts.export, "protect evaluator files",
            )

        rc = 127
        output = ""
        timed_out = False
        reward: float | None = None
        gates: dict[str, dict[str, Any]] = {}
        try:
            # Hidden verifiers must evaluate the task workspace declared by the
            # runtime rather than assuming a conventional path such as
            # ``/workspace/project``.  This matters for catalog-backed tasks,
            # whose workspaces are namespaced under ``/workspace/tasks``.
            verifier_command = (
                f"SWECLAR_PROJECT_DIR={_shell_quote(self.spec.workspace_path)} "
                f"{verifier.command}"
            )
            evidence["phase"] = "execution"
            evidence["ran"] = True
            rc, output, timed_out = self._execute(
                session_id,
                verifier_command,
                timeout=self.spec.timeouts.verifier,
                user=0 if self.spec.candidate_uid is not None else None,
            )
            evidence.update(returncode=rc, output=output, timed_out=timed_out, phase="readback")
            reward_text = self._read_container_text(name, verifier.reward_path)
            evidence["reward_text"] = reward_text
            gates_text = self._read_container_text(name, verifier.gates_path)
            evidence["gates_text"] = gates_text
            reward = _parse_reward(reward_text)
            gates = _parse_gates(gates_text)
            evidence.update(reward=reward, gates=gates)
        except Exception as error:
            evidence["error"] = {
                "type": type(error).__name__, "message": str(error), "phase": evidence["phase"],
            }
            raise
        finally:
            # Persist raw evidence before any container-side deletion. The outer
            # wrapper records the final outcome too, including cleanup failures.
            self._persist_verifier_evidence(workdir, evidence)
            evidence["phase"] = "cleanup"
            try:
                # A verifier may edit or commit inside the repository.  Restore the
                # frozen Candidate snapshot before the final source export.
                self._git_checked(name, ["reset", "--hard", saved_head], "restore candidate HEAD")
                self._git_checked(name, ["clean", "-fd"], "remove verifier worktree files")
                self._container_shell_checked(
                    name,
                    f"rm -rf -- {_shell_quote(verifier.container_path)} && "
                    f"rm -f -- {_shell_quote(verifier.reward_path)} "
                    f"{_shell_quote(verifier.gates_path)}",
                    self.spec.timeouts.export,
                    "remove verifier assets",
                )
                self._export_archive(name, workdir / "deliverable")
            except Exception as error:
                evidence["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
                raise

        return {
            "ran": True,
            "returncode": rc,
            "timed_out": timed_out,
            "output": output,
            "reward": reward,
            "gates": gates,
            "official_expected_gate_ids": list(verifier.expected_gate_ids),
            "test_results": _map_gate_results(verifier.gate_mapping, gates),
            "snapshot": snapshot,
        }

    def cleanup(self, session_id: str) -> None:
        self._remove_container(self._container_name(session_id))

    def _container_name(self, session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a nonempty string")
        readable = _CONTAINER_COMPONENT_RE.sub("-", session_id.casefold()).strip("-.")
        readable = readable[:34] or "run"
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
        return f"sweclar-{readable}-{digest}"

    def _ensure_image(self) -> None:
        inspect = self._image_inspect()
        if inspect is None:
            self._checked(
                ["docker", "pull", *(["--platform", self.spec.platform] if self.spec.platform else []), self.spec.image_ref],
                self.spec.timeouts.prepare,
                "pull digest-pinned task image",
            )
            inspect = self._image_inspect()
        if inspect is None:
            raise TaskRuntimeError("digest-pinned task image is unavailable after pull")
        expected = self.spec.image_ref.rsplit("@", 1)[1]
        if not any(str(item).endswith("@" + expected) for item in inspect):
            raise TaskRuntimeError("local task image does not expose the expected RepoDigest")

    def _image_inspect(self) -> list[str] | None:
        def _run(with_platform: bool) -> subprocess.CompletedProcess[str]:
            platform_args = (
                ["--platform", self.spec.platform]
                if with_platform and self.spec.platform
                else []
            )
            return subprocess.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    *platform_args,
                    self.spec.image_ref,
                    "--format",
                    "{{json .RepoDigests}}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

        result = _run(with_platform=True)
        # ``docker image inspect`` only learned ``--platform`` recently.  The
        # image is already digest-pinned, so the flag adds nothing on clients
        # that lack it; retry without it instead of reporting the image as
        # unavailable.
        if result.returncode != 0 and "unknown flag: --platform" in (result.stderr or ""):
            result = _run(with_platform=False)
        if result.returncode != 0:
            return None
        try:
            value = json.loads(result.stdout or "null")
        except json.JSONDecodeError as error:
            raise TaskRuntimeError("docker returned invalid image metadata") from error
        if not isinstance(value, list):
            raise TaskRuntimeError("docker image metadata omitted RepoDigests")
        return [str(item) for item in value]

    def _extra_container_args(self, name: str) -> list[str]:
        return []

    def _create_container(self, name: str) -> None:
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            *(["--platform", self.spec.platform] if self.spec.platform else []),
            "--label",
            "sweclar.runtime.managed=true",
            "--label",
            f"sweclar.runtime.fingerprint={self._fingerprint}",
            "--network",
            "none",
            "--cpus",
            str(self.spec.resources.cpus),
            "--memory",
            self.spec.resources.memory,
            "--pids-limit",
            str(self.spec.resources.pids_limit),
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--shm-size",
            self.spec.resources.shm_size,
            *(["--read-only", "--memory-swap", self.spec.resources.memory,
               *[item for path, options in self._tmpfs_mounts().items()
                 for item in ("--tmpfs", f"{path}:{options}")]]
              if self.spec.resources.workspace_size is not None else []),
            *(["--user", "0:0", "--cap-add", "CHOWN", "--cap-add", "SETUID",
               "--cap-add", "SETGID", "--cap-add", "KILL"]
              if self.spec.candidate_uid is not None else []),
            *self._extra_container_args(name),
            "--workdir",
            self.spec.workspace_path,
            "--entrypoint",
            "/bin/sh",
            self.spec.image_ref,
            "-c",
            "trap 'exit 0' TERM INT; while :; do sleep 3600; done",
        ]
        self._checked(args, self.spec.timeouts.prepare, "create task container")
        container = self._inspect_container(name)
        if container is None or not self._is_expected_container(container):
            raise TaskRuntimeError("created task container failed runtime validation")

    def _tmpfs_mounts(self) -> dict[str, str]:
        resources = self.spec.resources
        if resources.workspace_size is None:
            return {}
        execution = "exec" if resources.workspace_executable else "noexec"
        return {
            self.spec.workspace_path: f"rw,nosuid,nodev,{execution},size={resources.workspace_size},mode=0755",
            "/tmp": f"rw,nosuid,nodev,{execution},size={resources.temporary_size},mode=1777",
            "/private": f"rw,nosuid,nodev,noexec,size={resources.verifier_size},mode=0700",
            **({"/public_tests": "rw,nosuid,nodev,exec,size=64m,mode=0700"}
               if self.spec.phase_sealed_support else {}),
        }

    def _seed_workspace(self, name: str) -> None:
        """Copy the pinned repository into its bounded mount before agent work.

        A stopped, never executed image container exposes the original files
        hidden by the new tmpfs. No host project or hidden verifier is copied.
        """
        with tempfile.TemporaryDirectory(prefix="sweclar-image-seed-") as directory:
            seed = name + "-seed-" + Path(directory).name[-8:]
            created = self._checked(
                ["docker", "create", "--name", seed, "--network", "none",
                 *(["--platform", self.spec.platform] if self.spec.platform else []),
                 "--entrypoint", "/bin/sh", self.spec.image_ref, "-c", "exit 0"],
                self.spec.timeouts.prepare, "create pinned workspace seed",
            )
            seed_id = created.stdout.strip()
            if not re.fullmatch("[0-9a-f]{64}", seed_id):
                raise TaskRuntimeError("Seed create did not return full container ID")
            if not hasattr(self, "owned_seeds"):
                self.owned_seeds = {}
            self.owned_seeds[seed] = seed_id
            try:
                self._checked(
                    ["docker", "cp", f"{seed}:{self.spec.workspace_path}/.", directory],
                    self.spec.timeouts.prepare, "export pinned workspace seed",
                )
                self._copy_into_container(name, Path(directory), self.spec.workspace_path, "populate bounded workspace")
                self._container_shell_checked(
                    name, "chmod 755 " + _shell_quote(self.spec.workspace_path)
                    + f" && chown -R {self.spec.candidate_uid}:{self.spec.candidate_uid} "
                    + _shell_quote(self.spec.workspace_path),
                    self.spec.timeouts.prepare, "set workspace owner",
                )
            finally:
                self._remove_container(seed)

    def _copy_into_container(self, name: str, source: Path, destination: str, operation: str) -> None:
        if self.spec.resources.workspace_size is None:
            self._checked(
                ["docker", "cp", str(source) + ("/." if source.is_dir() else ""),
                 f"{name}:{destination}" + ("/" if source.is_dir() else "")],
                self.spec.timeouts.export, operation,
            )
            return
        # Docker cp rejects a read-only root even when the destination is a
        # writable tmpfs. Stream into that mount without relaxing root protection.
        target = PurePosixPath(destination)
        parent = str(target if source.is_dir() else target.parent)
        with tempfile.TemporaryFile() as payload:
            with tarfile.open(fileobj=payload, mode="w") as archive:
                archive.add(source, arcname="." if source.is_dir() else target.name)
            payload.seek(0)
            try:
                result = subprocess.run(
                    ["docker", "exec", "-i", "--user", "0:0", name,
                     "tar", "--no-same-owner", "-xpf", "-", "-C", parent],
                    stdin=payload, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", timeout=self.spec.timeouts.export,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise TaskRuntimeError(f"{operation} failed: {type(error).__name__}") from error
        if result.returncode != 0:
            raise TaskRuntimeError(f"{operation} failed: {(result.stdout or '')[-1200:]}")

    def _inspect_container(self, name: str) -> dict[str, Any] | None:
        result = subprocess.run(
            ["docker", "inspect", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return None
        try:
            document = json.loads(result.stdout or "null")
        except json.JSONDecodeError as error:
            raise TaskRuntimeError("docker returned invalid container metadata") from error
        if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
            raise TaskRuntimeError("docker returned malformed container metadata")
        return document[0]

    @staticmethod
    def _is_managed_container(container: Mapping[str, Any]) -> bool:
        labels = container.get("Config", {}).get("Labels") or {}
        return labels.get("sweclar.runtime.managed") == "true"

    def _is_expected_container(self, container: Mapping[str, Any]) -> bool:
        config = container.get("Config", {})
        labels = config.get("Labels") or {}
        host = container.get("HostConfig", {})
        return (
            self._is_managed_container(container)
            and labels.get("sweclar.runtime.fingerprint") == self._fingerprint
            and config.get("Image") == self.spec.image_ref
            and host.get("NetworkMode") == "none"
            and (self.spec.resources.workspace_size is None or (
                host.get("ReadonlyRootfs") is True
                and host.get("Tmpfs") == self._tmpfs_mounts()
                and host.get("Memory") == _docker_bytes(self.spec.resources.memory)
                and host.get("MemorySwap") == _docker_bytes(self.spec.resources.memory)
                and host.get("NanoCpus") == round(self.spec.resources.cpus * 1_000_000_000)
                and host.get("PidsLimit") == self.spec.resources.pids_limit
                and host.get("ShmSize") == _docker_bytes(self.spec.resources.shm_size)
            ))
        )

    def _require_running_container(self, name: str) -> None:
        container = self._inspect_container(name)
        if container is None:
            raise TaskRuntimeError("task container is missing; call prepare before execute")
        if not self._is_expected_container(container):
            raise TaskRuntimeError("task container does not match the frozen runtime")
        if not bool(container.get("State", {}).get("Running")):
            if self.spec.resources.workspace_size is not None:
                raise TaskRuntimeError("bounded task container stopped; call prepare to restore the persisted checkpoint")
            self._checked(["docker", "start", name], self.spec.timeouts.prepare, "start container")

    def _remove_container(self, name: str) -> None:
        if not hasattr(self, "_bounded_remover"):
            self._container_cleanup_events = []
            self._bounded_remover = BoundedRemoval(
                self._cleanup_owned, self._container_cleanup_events.append)
        self._bounded_remover.remove(name)

    def _cleanup_owned(self, container):
                if self._is_expected_container(container):
                    return True
                # Seed containers are intentionally unlabelled and never started.
                # Only names created by this exact runtime instance are eligible.
                return (getattr(self, "owned_seeds", {}).get(container.get('Name', '').lstrip('/')) == container.get('Id')
                        and bool(container.get('Id'))
                        and container.get('Config', {}).get('Image') == self.spec.image_ref
                        and container.get('HostConfig', {}).get('NetworkMode') == 'none'
                        and container.get('State', {}).get('Status') in ('created', 'removing')
                        and not container.get('State', {}).get('Running'))

    def _verify_pristine_base(self, name: str) -> None:
        head = self._git_text(name, ["rev-parse", "HEAD"], "read image base commit").strip()
        if not _commit_matches(head, self.spec.base_commit):
            raise TaskRuntimeError(
                f"task image HEAD does not match declared base commit {self.spec.base_commit}"
            )
        status = self._git_text(
            name, ["status", "--porcelain"], "inspect image worktree"
        )
        if status.strip():
            raise TaskRuntimeError("task image repository is not pristine")

    def _verify_base_ancestry(self, name: str) -> None:
        result = self._git_result(
            name,
            ["merge-base", "--is-ancestor", self.spec.base_commit, "HEAD"],
        )
        if result.returncode != 0:
            raise TaskRuntimeError("candidate repository no longer descends from the frozen base")

    def _restore_patch(self, name: str, patch_path: Path) -> None:
        container_patch = "/tmp/sweclar-task-runtime.patch"
        self._copy_into_container(name, patch_path, container_patch, "restore task patch")
        try:
            self._git_checked(
                name,
                ["apply", "--binary", "--index", container_patch],
                "apply persisted task patch",
            )
            self._git_checked(
                name,
                [
                    "-c",
                    "user.name=SWE-Clar",
                    "-c",
                    "user.email=benchmark@local",
                    "commit",
                    "-m",
                    "sweclar: restore persisted candidate patch",
                ],
                "commit restored task patch",
            )
            restored = self._git_bytes(
                name,
                [
                    "diff",
                    "--binary",
                    "--full-index",
                    f"{self.spec.base_commit}..HEAD",
                    "--",
                    *_SOURCE_PATHSPEC,
                ],
                "verify restored task patch",
            )
            if hashlib.sha256(restored).digest() != hashlib.sha256(patch_path.read_bytes()).digest():
                raise TaskRuntimeError("restored candidate patch differs from persisted patch")
        finally:
            self._container_shell_checked(
                name,
                f"rm -f -- {_shell_quote(container_patch)}",
                30,
                "remove temporary task patch",
            )

    def _export_archive(self, name: str, destination: Path) -> None:
        archive = self._git_bytes(
            name,
            ["archive", "--format=tar", "HEAD", "--", *_SOURCE_PATHSPEC],
            "export candidate repository",
        )
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=".sweclar-export-", dir=str(parent))
        )
        try:
            _safe_extract_tar(archive, temporary)
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            elif destination.exists():
                shutil.rmtree(destination)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _resolve_tests_dir(self, tests_dir: Path | str) -> Path:
        supplied = Path(tests_dir).resolve()
        bundle = self.spec.bundle_dir
        if bundle is None:
            candidate = supplied / self.spec.verifier.host_tests_path
            if not candidate.is_dir() and supplied.is_dir():
                candidate = supplied
            return candidate.resolve()

        expected = (bundle / self.spec.verifier.host_tests_path).resolve()
        try:
            expected.relative_to(bundle)
        except ValueError:
            raise TaskRuntimeConfigError("verifier host path escapes the V4 bundle") from None
        if supplied not in {bundle, expected}:
            joined = (supplied / self.spec.verifier.host_tests_path).resolve()
            if joined != expected:
                raise TaskRuntimeError("tests_dir does not resolve to the frozen verifier assets")
        if not expected.is_dir():
            raise TaskRuntimeError("official verifier asset directory is missing")
        return expected

    def _read_container_text(self, name: str, path: str) -> str | None:
        result = subprocess.run(
            ["docker", "exec", name, "cat", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        return (result.stdout or b"").decode("utf-8", errors="replace")

    def _git_result(self, name: str, arguments: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "docker",
                "exec",
                "--workdir",
                self.spec.workspace_path,
                *(["--user", f"{self.spec.candidate_uid}:{self.spec.candidate_uid}"]
                  if self.spec.candidate_uid is not None else []),
                name,
                "git",
                "-C",
                self.spec.workspace_path,
                *arguments,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.spec.timeouts.export,
        )

    def _git_checked(self, name: str, arguments: list[str], operation: str) -> None:
        result = self._git_result(name, arguments)
        if result.returncode != 0:
            raise TaskRuntimeError(
                f"{operation} failed: {_safe_process_output(result)[-1200:]}"
            )

    def _git_text(self, name: str, arguments: list[str], operation: str) -> str:
        value = self._git_bytes(name, arguments, operation)
        return value.decode("utf-8", errors="replace")

    def _git_bytes(self, name: str, arguments: list[str], operation: str) -> bytes:
        result = self._git_result(name, arguments)
        if result.returncode != 0:
            raise TaskRuntimeError(
                f"{operation} failed: {_safe_process_output(result)[-1200:]}"
            )
        return result.stdout or b""

    def _container_shell_checked(
        self,
        name: str,
        command: str,
        timeout: int,
        operation: str,
    ) -> None:
        self._checked(
            ["docker", "exec", name, "/bin/sh", "-c", command],
            timeout,
            operation,
        )

    @staticmethod
    def _checked(
        arguments: list[str],
        timeout: int,
        operation: str,
    ) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TaskRuntimeError(f"{operation} failed: {type(error).__name__}") from error
        if result.returncode != 0:
            output = (result.stdout or "")[-1200:]
            raise TaskRuntimeError(f"{operation} failed: {output}")
        return result

    def _validate_marker(self, marker_path: Path) -> None:
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TaskRuntimeError("persisted runtime marker is invalid") from error
        if not isinstance(marker, dict) or marker.get("fingerprint") != self._fingerprint:
            raise TaskRuntimeError("persisted workdir belongs to a different task runtime")

    def _write_marker(self, marker_path: Path) -> None:
        document = {
            "schema_version": 1,
            "fingerprint": self._fingerprint,
            "image_ref": self.spec.image_ref,
            "base_commit": self.spec.base_commit,
            "workspace_path": self.spec.workspace_path,
        }
        _atomic_write(
            marker_path,
            (json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )


def _validated_tool_env(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("tool_env must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or _ENV_NAME_RE.fullmatch(key) is None:
            raise ValueError("tool_env contains an invalid environment name")
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("tool_env values must be NUL-free strings")
        result[key] = item
    return result


def _safe_relative_posix_path(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError(f"{field} must be a nonempty POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field} must be a normalized relative POSIX path")
    return path.as_posix()


def _safe_absolute_posix_path(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError(f"{field} must be a nonempty POSIX path")
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise ValueError(f"{field} must be a normalized absolute POSIX path")
    return path.as_posix()


def _commit_matches(actual: str, expected: str) -> bool:
    return bool(_COMMIT_RE.fullmatch(actual)) and actual.startswith(expected)


def _timeout_output(error: subprocess.TimeoutExpired) -> str:
    value = error.stdout or b""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_process_output(result: subprocess.CompletedProcess) -> str:
    value = (result.stdout or b"") + (result.stderr or b"")
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def _shell_quote(value: str) -> str:
    # Config paths are already normalized; single quoting prevents glob/option
    # interpretation if future schemas permit additional safe characters.
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _validate_verifier_tree(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise TaskRuntimeError("official verifier assets must be a real directory")
    total = 0
    for item in path.rglob("*"):
        if item.is_symlink():
            raise TaskRuntimeError("official verifier assets cannot contain symlinks")
        if item.is_dir():
            continue
        if not item.is_file():
            raise TaskRuntimeError("official verifier assets contain a special file")
        total += item.stat().st_size
        if total > _MAX_VERIFIER_BYTES:
            raise TaskRuntimeError("official verifier assets exceed the size limit")


def _parse_reward(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        reward = float(value.strip())
    except (TypeError, ValueError):
        return None
    return reward if math.isfinite(reward) else None


class _DuplicateJSONKey(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _strict_json_loads(value: str) -> Any:
    return json.loads(value, object_pairs_hook=_strict_json_object)


def _parse_gates(value: str | None) -> dict[str, dict[str, Any]]:
    if value is None or not value.strip():
        return {}
    documents: list[Any]
    try:
        documents = [_strict_json_loads(value)]
    except json.JSONDecodeError:
        documents = []
        for line in value.splitlines():
            if not line.strip():
                continue
            try:
                documents.append(_strict_json_loads(line))
            except (json.JSONDecodeError, _DuplicateJSONKey):
                return {}
    except _DuplicateJSONKey:
        return {}

    raw_items: list[Any] = []
    for document in documents:
        if isinstance(document, list):
            raw_items.extend(document)
        elif isinstance(document, dict) and isinstance(document.get("gates"), list):
            raw_items.extend(document["gates"])
        elif isinstance(document, dict) and isinstance(document.get("gates"), dict):
            raw_items.extend(
                {"id": gate_id, **(record if isinstance(record, dict) else {"verdict": record})}
                for gate_id, record in document["gates"].items()
            )
        elif isinstance(document, dict) and any(key in document for key in ("id", "gate_id")):
            raw_items.append(document)
        elif isinstance(document, dict):
            raw_items.extend(
                {"id": gate_id, **(record if isinstance(record, dict) else {"verdict": record})}
                for gate_id, record in document.items()
            )

    normalized: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        gate_id = item.get("id", item.get("gate_id"))
        if not isinstance(gate_id, str) or not gate_id:
            continue
        if gate_id in normalized:
            # Duplicate gate observations are ambiguous and must never be
            # silently reduced by last-write-wins semantics.
            return {}
        skipped = bool(item.get("skipped", False))
        verdict = item.get("verdict", item.get("passed", item.get("status")))
        passed = _verdict_passed(verdict)
        detail = item.get("detail", item.get("message", ""))
        normalized[gate_id] = {
            "passed": bool(passed) and not skipped,
            "skipped": skipped,
            "detail": str(detail),
            "verdict": verdict,
        }
    return normalized


def _verdict_passed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value > 0
    if isinstance(value, str):
        return value.strip().casefold() in {
            "pass",
            "passed",
            "true",
            "success",
            "succeeded",
            "ok",
            "1",
        }
    return False


def _map_gate_results(
    mapping: Mapping[str, RuntimeGateMapping],
    gates: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for test_id, rule in mapping.items():
        records = [gates.get(gate_id) for gate_id in rule.all_of]
        missing = [
            gate_id
            for gate_id, record in zip(rule.all_of, records, strict=True)
            if record is None
        ]
        explicit_failures = [
            gate_id
            for gate_id, record in zip(rule.all_of, records, strict=True)
            if record is not None and not record.get("passed") and not record.get("skipped")
        ]
        skipped_ids = [
            gate_id
            for gate_id, record in zip(rule.all_of, records, strict=True)
            if record is not None and record.get("skipped")
        ]
        passed = not missing and not explicit_failures and not skipped_ids
        detail_parts = []
        for gate_id, record in zip(rule.all_of, records, strict=True):
            if record is None:
                detail_parts.append(f"{gate_id}=missing")
            elif record.get("skipped"):
                detail_parts.append(f"{gate_id}=skipped")
            elif record.get("passed"):
                detail_parts.append(f"{gate_id}=pass")
            else:
                detail_parts.append(f"{gate_id}=fail")
        results[test_id] = {
            "passed": passed,
            # Missing official gates are failures, never score-excluding skips.
            "skipped": bool(skipped_ids) and not missing and not explicit_failures,
            "detail": "; ".join(detail_parts),
        }
    return results


def _safe_extract_tar(data: bytes, destination: Path) -> None:
    """Extract a tar archive without traversal, device, or symlink-pivot writes."""

    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    links: list[tarfile.TarInfo] = []
    seen: set[Path] = set()
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError as error:
        raise TaskRuntimeError("git archive returned an invalid tar stream") from error
    with archive:
        members = archive.getmembers()
        directory_modes: list[tuple[Path, int]] = []
        for member in members:
            member_parts = PurePosixPath(member.name).parts
            if any(part in _VENDOR_PARTS for part in member_parts):
                continue
            count += 1
            total += max(0, member.size)
            if count > _MAX_ARCHIVE_MEMBERS or total > _MAX_ARCHIVE_BYTES:
                raise TaskRuntimeError("task source archive exceeds safety limits")
            target = _archive_target(root, member.name)
            if target in seen:
                raise TaskRuntimeError("task source archive contains duplicate paths")
            seen.add(target)
            if member.issym() or member.islnk():
                links.append(member)
                continue
            if not (member.isdir() or member.isfile()):
                raise TaskRuntimeError("task source archive contains a special file")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                directory_modes.append((target, member.mode & 0o777))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise TaskRuntimeError("task source archive contains an unreadable file")
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            target.chmod(member.mode & 0o777)

        # Links are created last, so no later regular-file extraction can pivot
        # through a just-created symlink.
        for member in links:
            target = _archive_target(root, member.name)
            if target.exists() or target.is_symlink():
                raise TaskRuntimeError("task source archive link collides with a path")
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or "\\" in member.linkname:
                    raise TaskRuntimeError("task source archive has an unsafe symlink")
                resolved = (target.parent / Path(*link.parts)).resolve(strict=False)
                try:
                    resolved.relative_to(root)
                except ValueError:
                    raise TaskRuntimeError("task source archive symlink escapes export") from None
                os.symlink(member.linkname, target)
            else:
                source = _archive_target(root, member.linkname)
                if not source.is_file() or source.is_symlink():
                    raise TaskRuntimeError("task source archive has an unsafe hardlink")
                os.link(source, target)
        for target, mode in reversed(directory_modes):
            target.chmod(mode)


def _archive_target(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise TaskRuntimeError("task source archive contains an unsafe path")
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise TaskRuntimeError("task source archive path escapes export")
    parts = [part for part in pure.parts if part not in {"", "."}]
    if not parts:
        raise TaskRuntimeError("task source archive contains an empty path")
    target = root.joinpath(*parts)
    try:
        target.relative_to(root)
    except ValueError:
        raise TaskRuntimeError("task source archive path escapes export") from None
    return target
