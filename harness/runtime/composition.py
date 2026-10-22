"""Compose the benchmark without importing an HTTP server."""
from __future__ import annotations
import hashlib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from llm import RoleConfig
from .canonical import digest_json
from .registry import load_registry
from .manifests import manifest_from_registry
from .run_contract import execution_contract
from .execution import ExecutionContext
from .layout import workspace_path, attachment_root

def _runtime_safe_role_snapshot(cfg: RoleConfig, *, source_role: str) -> dict:
    return {
        "request_settings_digest": digest_json({
            key: value for key, value in vars(cfg.resolved_for_call()).items()
            if key != "api_key"
        }),
        "source_role": source_role,
        "api_style": cfg.api_style,
        "base_url": _runtime_safe_endpoint(cfg.base_url),
        "model": cfg.model,
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "max_tokens": cfg.max_tokens,
        "thinking": cfg.thinking,
        "seed": cfg.seed,
        "extra_header_names": sorted(cfg.extra_headers),
    }

def _runtime_safe_pi_profile_snapshot(profile: dict, *, role: str) -> dict:
    return {
        "request_settings_digest": digest_json({
            key: value for key, value in profile.items()
            if key not in {"api_key", "auth_path", "available"}
        }),
        "source_role": "model_under_test",
        "target_role": role,
        "profile_id": profile["profile_id"],
        "label": profile["label"],
        "provider": profile["provider"],
        "model": profile["model"],
        "api": profile.get("api"),
        "harness": "pi-coding-agent",
        "harness_version": "0.73.1",
        "thinking": profile.get("thinking"),
        "max_tokens": profile.get("max_tokens"),
    }

def _runtime_safe_endpoint(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""
    if not parsed.scheme or not hostname:
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))

def _runtime_ru_attachment_source(task_root: Path, agent_path: str) -> Path:
    """Resolve one candidate-visible attachment inside the trusted raw root."""

    resolved_root = attachment_root(task_root).resolve()
    prefix = "task_attachments/"
    if not agent_path.startswith(prefix):
        raise RuntimeError(f"invalid Requirement Unit attachment path: {agent_path}")
    relative = agent_path.removeprefix(prefix)
    source_path = (resolved_root / relative).resolve()
    try:
        source_path.relative_to(resolved_root)
    except ValueError:
        raise RuntimeError(
            f"Requirement Unit attachment escapes raw/attachments: {agent_path}"
        ) from None
    if not source_path.is_file() or source_path.is_symlink():
        raise RuntimeError(f"Requirement Unit attachment is missing: {agent_path}")
    return source_path

def _runtime_ru_attachment_manifest(task_root: Path, agent_paths: list[str]):
    """Hash allowlisted raw attachments while exposing only workspace paths."""

    from runtime.freeze import AttachmentManifestItem

    records = []
    for index, agent_path in enumerate(agent_paths, start=1):
        source_path = _runtime_ru_attachment_source(task_root, agent_path)
        records.append(
            AttachmentManifestItem(
                attachment_id=f"attachment-{index}",
                path=agent_path,
                size=source_path.stat().st_size,
                digest="sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest(),
            )
        )
    return records

def build_engine(
    task_id: str,
    *, tasks_dir: Path, state_dir: Path, profile: dict, client_config: RoleConfig, judge_config: RoleConfig, supervisor_config: RoleConfig | None = None, tool_env=None, progress=None, workdirs_dir=None, audit_scoring='legacy',
):
    """Build stateless adapters around the durable interactive run document."""

    from runtime.artifacts import ArtifactStore
    from runtime.canonical import digest_json
    from runtime.client import SupervisedClientSimulator
    from runtime.dialogue import DialogueService
    from runtime.freeze import AttachmentManifestItem
    from runtime.role_adapters import (
        ClientSimulatorTransport,
        DisclosureSupervisorTransport,
        SemanticAuditJudge,
    )
    from runtime.pi_adapters import PiAuditTurn, PiCandidateTurn
    from runtime.registry import load_source_index
    from runtime.step_engine import StepEngine
    from runtime.storage import SessionRepository
    from runtime.task_input import build_initial_task_input
    from runtime.task_runtime import load_task_runtime

    execution = ExecutionContext(tasks_dir=tasks_dir, workdirs_dir=workdirs_dir or state_dir / "workdirs", auth_path=profile.get("auth_path", Path.home()/".pi/agent/auth.json"), tool_env=tool_env, progress=progress)
    task_root = execution._runtime_task_bundle(task_id)
    registry = load_registry(task_root)
    manifest = manifest_from_registry(registry)
    sources = list(load_source_index(task_root).values())
    runtime_spec = load_task_runtime(task_root)
    if runtime_spec is None:
        raise ValueError(f"Task {task_id} requires a managed runtime")
    initial_input = build_initial_task_input(task_root, registry)
    from runtime.delivery_contract import private_project_context
    project_context, private_read_roots = private_project_context(task_root, registry, workspace=runtime_spec.workspace_path)
    candidate_read_roots: list[dict[str, object]] = []
    public_attachment_sources: dict[str, str] = {}
    if initial_input is not None:
        public_task = initial_input.public_task
        attachments = _runtime_ru_attachment_manifest(
            task_root, initial_input.attachment_paths
        )
        public_attachment_sources = {
            agent_path: str(_runtime_ru_attachment_source(task_root, agent_path))
            for agent_path in initial_input.attachment_paths
        }
        sources = [*sources, *initial_input.source_catalog]
        if runtime_spec is not None:
            candidate_read_roots = [
                {
                    "virtual": f"{runtime_spec.workspace_path.rstrip('/')}/task_attachments",
                    "real": str(attachment_root(task_root).resolve()),
                },
                {
                    "virtual": runtime_spec.workspace_path,
                    "real": str(workspace_path(task_root).resolve()),
                    "workspace": True,
                },
            ]
    if initial_input.public_test_paths:
        candidate_read_roots.append({
            "virtual": "/public_tests",
            "real": str((task_root / "public_tests").resolve()),
        })
    from runtime.public_sources import public_source_roots
    # Only task workspace and attachments are candidate inputs in this pilot.
    target_profile = dict(profile)
    source_configs = {"client": client_config, "judge": judge_config}
    configs = {
        name: source_configs[role]
        for name, role in {
            "audit_judge": "judge",
            "client_simulator": "client",
            "disclosure_supervisor": "judge",
        }.items()
    }
    if supervisor_config is not None:
        configs['disclosure_supervisor'] = supervisor_config
    candidate_runtime_provider, candidate_runtime_cleanup = (
        execution._runtime_pi_disposable_runtime(
            runtime_spec,
            public_attachment_sources,
            "clarification",
        )
    )
    audit_runtime_provider, audit_runtime_cleanup = (
        execution._runtime_pi_disposable_runtime(
            runtime_spec,
            public_attachment_sources,
            "audit",
        )
    )
    candidate = PiCandidateTurn(
        target_profile,
        read_roots=candidate_read_roots,
        runtime_provider=candidate_runtime_provider,
        runtime_cleanup=candidate_runtime_cleanup,
    )
    client_simulator = ClientSimulatorTransport(configs["client_simulator"], read_roots=private_read_roots)
    disclosure_supervisor = DisclosureSupervisorTransport(
        configs["disclosure_supervisor"],
        read_roots=private_read_roots,
    )
    audit = PiAuditTurn(
        target_profile,
        read_roots=candidate_read_roots,
        runtime_provider=audit_runtime_provider,
        runtime_cleanup=audit_runtime_cleanup,
    )
    audit_judge = SemanticAuditJudge(configs["audit_judge"])
    if audit_scoring == 'ru_tiered_v1':
        from runtime.tiered_audit import TieredAuditJudge
        audit_judge = TieredAuditJudge(configs['audit_judge'],task_root=task_root,registry=registry,cache_dir=state_dir/'tiered-audit-cache')
    elif audit_scoring != 'legacy':
        raise ValueError('Unknown Audit scoring protocol')

    def dialogue_factory(repository, frozen_registry):
        return DialogueService(
            repository,
            frozen_registry,
            supervised_client=SupervisedClientSimulator(
                frozen_registry,
                client_simulator,
                disclosure_supervisor,
                project_context=project_context,
            ),
        )

    profile_snapshot = {
        "candidate": _runtime_safe_pi_profile_snapshot(
            target_profile, role="candidate"
        ),
        "audit": _runtime_safe_pi_profile_snapshot(target_profile, role="audit"),
        "coding": _runtime_safe_pi_profile_snapshot(target_profile, role="coding"),
        **{
            name: _runtime_safe_role_snapshot(config, source_role={
                        "client_rewrite": "client", "audit_judge": "judge",
                "client_simulator": "client",
                "disclosure_supervisor": "supervisor" if supervisor_config is not None else "judge",
            }[name])
            for name, config in configs.items()
        },
    }
    engine = StepEngine(
        repository=SessionRepository(state_dir / "sessions.sqlite3"),
        artifacts=ArtifactStore(state_dir / "artifacts"),
        registry=registry,
        manifest=manifest,
        dialogue_service_factory=dialogue_factory,
        candidate_turn=candidate,
        audit_turn=audit,
        audit_judge=audit_judge,
        audit_judge_model=configs["audit_judge"].model,
        coding_step=execution._runtime_pi_coding_step_callback(
            target_profile,
            task_id,
            runtime_spec,
            public_attachment_sources,
        ),
        coding_evaluator=execution._runtime_coding_evaluator(task_id, runtime_spec),
        public_task=public_task,
        oracle_project_readme=project_context.get('project_readme',''),
        source_catalog=sources,
        attachments=attachments,
        candidate_config_digest=digest_json(profile_snapshot["candidate"]),
        run_contract=execution_contract(
            Path(__file__).resolve().parent.parent, task_root, profile_snapshot, runtime_spec.provenance()
        ),
        official_expected_gate_ids_digest=(
            digest_json(runtime_spec.verifier.expected_gate_ids)
            if runtime_spec is not None
            and getattr(runtime_spec, "verifier", None) is not None
            else None
        ),
        verifier_digest=(
            runtime_spec.verifier_digest()
            if runtime_spec is not None
            and callable(getattr(runtime_spec, "verifier_digest", None))
            else None
        ),
    )
    return engine, profile_snapshot, {
        "PiCandidateTurn": candidate,
        "ClientSimulatorTransport": client_simulator,
        "DisclosureSupervisorTransport": disclosure_supervisor,
        "PiAuditTurn": audit,
        "SemanticAuditJudge": audit_judge,
    }
