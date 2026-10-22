"""Pi execution adapters shared by the CLI and optional web application."""
from __future__ import annotations
from uuid import uuid4
import json
import os
import subprocess
import time
from datetime import datetime, UTC
from pathlib import Path
from llm import RoleConfig, LLMError
import prompts
from .coding import CandidateCodingFailure
from .registry import load_registry
from .manifests import manifest_from_registry
from .live_progress import ProgressPersistenceGate
from .process_watchdog import consume_streamed_process, ProcessIdleTimeout, ProcessTotalTimeout

def now_iso():
    return datetime.now(UTC).isoformat()

class ExecutionContext:
    def __init__(self, *, tasks_dir, workdirs_dir, auth_path, tool_env=None, progress=None):
        self.tasks_dir = Path(tasks_dir).resolve()
        self.workdirs_dir = Path(workdirs_dir).resolve()
        self.auth_path = Path(auth_path).expanduser()
        self.tool_env = dict({"PAGER": "cat", "NO_COLOR": "1", "PIP_PROGRESS_BAR": "off"} if tool_env is None else tool_env)
        self.base_dir = Path(__file__).resolve().parent.parent
        self.progress = progress

    def _runtime_task_bundle(self, task_id):
        path = (self.tasks_dir / task_id).resolve()
        if path.parent != self.tasks_dir or not path.is_dir():
            raise ValueError("Unknown task: " + task_id)
        return path

    def _runtime_persist_pi_live(self, session_id, live):
        if self.progress is not None:
            self.progress(session_id, live)

    def _runtime_official_runtime(self, runtime_spec):
        from runtime.task_runtime import OfficialTaskRuntime

        return OfficialTaskRuntime(runtime_spec, self.tool_env)

    def _runtime_pi_disposable_runtime(self, 
        runtime_spec,
        public_attachment_sources: dict[str, str],
        phase: str,
    ):
        """Provide an isolated, disposable task sandbox to a non-Coding Pi turn."""

        if runtime_spec is None:
            return None, None

        def provide(context: dict) -> dict:
            runtime = self._runtime_official_runtime(runtime_spec)
            session_id = str(context.get("session_id") or "").strip()
            if not session_id:
                raise RuntimeError(f"{phase} Pi runtime requires a session_id")
            runtime_id = f"{session_id}-{phase}-inspect"
            runtime.prepare(runtime_id, self.workdirs_dir / runtime_id)
            runtime.stage_public_attachments(
                runtime_id,
                public_attachment_sources,
            )
            return {
                "runtime_container": runtime._container_name(runtime_id),
                "runtime_workspace": runtime_spec.workspace_path,
                "runtime_uid": getattr(runtime_spec, "candidate_uid", None),
                "command_timeout_s": runtime_spec.timeouts.command,
                "_runtime_session_id": runtime_id,
            }

        def cleanup(context: dict) -> None:
            runtime_id = str(context.get("_runtime_session_id") or "").strip()
            if runtime_id:
                self._runtime_official_runtime(runtime_spec).cleanup(runtime_id)

        return provide, cleanup

    @staticmethod
    def _runtime_official_gate_result(record):
        """Normalize one raw official gate for the manifest scorer.

        Runtime gate mappings are slot-oriented, but integration/basic gates are
        also first-class manifest tests.  Preserve their pass/fail/skipped state
        instead of silently dropping them at the V4 adapter boundary.
        """
        if not isinstance(record, dict):
            return None
        verdict = record.get("verdict")
        passed = record.get("passed")
        if not isinstance(passed, bool):
            passed = verdict is True or (
                isinstance(verdict, str)
                and verdict.strip().casefold() in {"pass", "passed", "true", "success", "succeeded", "ok", "1"}
            )
        return {
            "passed": passed,
            "skipped": bool(record.get("skipped")),
            "detail": record.get("detail", "official gate result"),
        }

    def _runtime_pi_coding_step_callback(self, 
        config: RoleConfig | dict,
        task_id: str,
        runtime_spec=None,
        public_attachment_sources: dict[str, str] | None = None,
    ):
        """Return the Pi-backed Coding Agent session adapter.

        V4 no longer parses a model reply as a fenced shell block.  Pi owns the
        coding loop and emits structured native Pi tool calls; this adapter supplies
        the public frozen context, binds Pi's tools to the isolated runtime, and
        persists Pi's full transcript for the Workspace timeline.
        """

        runner_path = self.base_dir / "pi" / "runner.mjs"
        if runtime_spec is None:
            raise ValueError("A managed task runtime is required")
        model_profile = dict(config)
        from .public_sources import public_source_roots
        public_environment = []

        def run(context: dict) -> dict:
            if not runner_path.exists():
                raise LLMError(f"Pi runner is not installed: {runner_path}")
            session = context["session"]
            delivery_id = f"{session['session_id']}-coding"
            host_workdir = self.workdirs_dir / delivery_id
            evidence = context["frozen_context"]["evidence"]
            transcript = [
                {"role": message.get("role"), "content": message.get("content")}
                for message in evidence.get("messages", [])
            ]
            runtime = None
            runtime_container = None
            runtime_workspace = None
            if runtime_spec is not None:
                runtime = self._runtime_official_runtime(runtime_spec)
                runtime.prepare(delivery_id, host_workdir)
                runtime.stage_public_attachments(
                    delivery_id,
                    public_attachment_sources or {},
                )
                # The task runtime deliberately keeps the Docker boundary in the
                # Python owner. Pi's native tool operations may only address this
                # exact managed container, never the host filesystem.
                runtime_container = runtime._container_name(delivery_id)
                runtime_workspace = runtime_spec.workspace_path
                instruction = (
                    "The isolated task repository is already mounted at "
                    f"{runtime_workspace}. Use Pi's native read, bash, edit, and write tools to inspect and edit "
                    "that repository directly. Run the project's build/tests and "
                    "leave the completed source in place. Do not use ./deliverable."
                )
            user_prompt = json.dumps(
                {
                    "task": evidence.get("public_task", ""),
                    "attachments": [item.get("path") for item in evidence.get("attachments", [])],
                    "frozen_dialogue": transcript,
                    "candidate_observations": evidence.get("candidate_observations", []),
                    "delivery_contract": context["basic_delivery_contract"],
                    "instruction": instruction,
                },
                ensure_ascii=False,
            )
            system_prompt = prompts.CODING_SYSTEM + "\n\n" + instruction
            effective = model_profile
            payload = {
                "session_kind": "coding",
                "model_config": {
                    key: value
                    for key, value in effective.items()
                    if key not in {
                        "api_key", "auth_path", "available", "auth_type",
                        "profile_id", "label",
                    }
                },
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "host_workdir": str(host_workdir),
                "runtime_container": runtime_container,
                "runtime_workspace": runtime_workspace,
                "runtime_public_read_files": {item['virtual']:item['files'][''] for item in public_environment},
                "runtime_uid": getattr(runtime_spec, "candidate_uid", None),
                "command_timeout_s": (
                    runtime_spec.timeouts.command if runtime_spec is not None else 300
                ),
                "auth_path": str(effective.get("auth_path") or self.auth_path),
                "agent_dir": str(
                    Path(effective.get("auth_path") or self.auth_path).parent
                ),
                "stream_progress": True,
            }
            live = {
                "status": "running",
                "backend": "pi-coding-agent",
                "backend_version": "0.73.1",
                "action_type": "pi_session",
                "started_at": now_iso(),
                "updated_at": now_iso(),
                "turn_count": 0,
                "tool_call_count": 0,
                "turns": [],
                "tool_events": [],
                "event_trace": [],
                "latest_assistant": None,
                "current_turn": None,
                "last_event": "session_started",
                "request": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "user_payload": json.loads(user_prompt),
                    "prompt_images": [],
                    "tool_permissions": ["read", "bash", "edit", "write", "submit_delivery"],
                },
            }
            self._runtime_persist_pi_live(session["session_id"], live)
            progress_persistence = ProgressPersistenceGate()

            def apply_live_progress(progress: dict) -> None:
                event_name = str(progress.get("event") or "progress")
                live["updated_at"] = now_iso()
                live["last_event"] = event_name
                if progress.get("assistant") is not None:
                    live["latest_assistant"] = progress.get("assistant")
                if event_name == "turn_started":
                    live["current_turn"] = progress.get("turn")
                elif event_name == "turn_completed":
                    turn = progress.get("turn")
                    if isinstance(turn, dict):
                        turns = [item for item in live["turns"] if item.get("turn_index") != turn.get("turn_index")]
                        turns.append(turn)
                        live["turns"] = sorted(turns, key=lambda item: item.get("turn_index", 0))
                        live["current_turn"] = None
                        live["latest_assistant"] = turn.get("assistant") or live.get("latest_assistant")
                elif event_name == "tool_completed":
                    tool_event = progress.get("tool_event")
                    if isinstance(tool_event, dict):
                        live["tool_events"].append(tool_event)
                    live["tool_call_count"] = int(progress.get("tool_call_count") or len(live["tool_events"]))
                trace = progress.get("trace")
                if isinstance(trace, dict):
                    live["event_trace"].append(trace)
                if event_name in {"tool_started", "tool_ended"}:
                    live["event_trace"].append({"type": event_name, **({"trace": trace} if isinstance(trace, dict) else {})})
                if progress.get("turn_count") is not None:
                    live["turn_count"] = int(progress.get("turn_count") or 0)
                live["tool_call_count"] = max(int(live.get("tool_call_count") or 0), len(live["tool_events"]))
                # Keep the live document bounded if a model emits an unusually
                # verbose event stream. The completed Pi result remains lossless.
                live["tool_events"] = live["tool_events"][-200:]
                live["event_trace"] = live["event_trace"][-400:]
                if progress_persistence.should_persist(event_name):
                    self._runtime_persist_pi_live(session["session_id"], live)

            def persist_partial_snapshot():
                try:
                    if runtime is None:
                        raise RuntimeError("Managed runtime missing")
                    return runtime.snapshot_and_export(delivery_id, host_workdir)
                except Exception:
                    # Preserve the original Pi failure. The runtime container is
                    # still available for an explicit Retry when a snapshot is
                    # temporarily unavailable.
                    return None

            started = time.monotonic()
            process_environment = {
                **os.environ,
                "SWECLAR_PI_MODEL_API_KEY": str(effective.get("api_key") or ""),
                "MINIMAX_API_KEY": str(effective.get("api_key") or ""),
            }
            process = subprocess.Popen(
                ["node", str(runner_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_environment,
                start_new_session=True,
            )
            try:
                assert process.stdin is not None
                process.stdin.write(json.dumps(payload, ensure_ascii=False))
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            streamed_result = None
            stdout_lines: list[str] = []

            def consume_stdout_line(raw_line: str) -> None:
                nonlocal streamed_result
                line = raw_line.strip()
                if not line:
                    return
                try:
                    envelope = json.loads(line)
                except json.JSONDecodeError:
                    stdout_lines.append(line)
                    return
                if isinstance(envelope, dict) and envelope.get("kind") == "pi_progress":
                    apply_live_progress(envelope)
                    return
                if isinstance(envelope, dict) and envelope.get("kind") == "pi_result":
                    streamed_result = envelope.get("result")
                    return
                stdout_lines.append(line)

            idle_timeout_s = max(
                1.0,
                float(os.environ.get("SWECLAR_PI_CODING_IDLE_TIMEOUT_SECONDS", "900")),
            )
            total_timeout_setting = os.environ.get(
                "SWECLAR_PI_CODING_TOTAL_TIMEOUT_SECONDS", ""
            ).strip()
            total_timeout_s = (
                max(idle_timeout_s, float(total_timeout_setting))
                if total_timeout_setting
                else None
            )
            try:
                outcome = consume_streamed_process(
                    process,
                    consume_stdout_line,
                    idle_timeout_s=idle_timeout_s,
                    total_timeout_s=total_timeout_s,
                )
            except (ProcessIdleTimeout, ProcessTotalTimeout) as error:
                live["status"] = "failed_retryable"
                live["updated_at"] = now_iso()
                live["last_event"] = "session_timeout"
                live["timeout"] = {
                    "kind": error.kind,
                    "limit_seconds": error.timeout_s,
                    "elapsed_seconds": round(error.elapsed_s, 3),
                }
                self._runtime_persist_pi_live(session["session_id"], live)
                persist_partial_snapshot()
                raise LLMError(
                    f"Pi Coding Agent {error.kind}; partial workspace is preserved for Retry"
                ) from error

            stderr = outcome.stderr
            returncode = outcome.returncode
            elapsed = round(outcome.elapsed_s, 3)
            stdout = streamed_result if isinstance(streamed_result, dict) else None

            result = stdout
            if result is None and stdout_lines:
                try:
                    result = json.loads(stdout_lines[-1])
                except json.JSONDecodeError as error:
                    persist_partial_snapshot()
                    detail = (stderr or "\n".join(stdout_lines))[-4000:]
                    raise LLMError(f"Pi returned invalid JSON: {detail}") from error
            if result is None:
                persist_partial_snapshot()
                detail = stderr[-4000:] or "Pi returned no result"
                raise LLMError(f"Pi returned invalid JSON: {detail}")
            if returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
                persist_partial_snapshot()
                if isinstance(result, dict) and isinstance(result.get('refusal'), dict):
                    error = LLMError('provider_refusal')
                    error.provider_refusal = True
                    raise error
                detail = (result or {}).get("error") if isinstance(result, dict) else None
                detail = detail or stderr[-4000:] or "unknown Pi failure"
                raise LLMError(f"Pi Coding Agent failed: {detail}")

            workflow = result.get("workflow_action")
            submitted = isinstance(workflow, dict) and workflow.get("action") == "delivery"
            stop_reason = (result.get("final_message") or {}).get("stop_reason")
            if not submitted and stop_reason not in {"stop", "length"}:
                persist_partial_snapshot()
                raise LLMError(
                    "Pi ended without a delivery or a completed model response; "
                    "the partial workspace is preserved for recovery"
                )
            delivery = workflow if submitted else {}
            delivery_summary = str(delivery.get("summary") or "").strip()
            delivery_checks = [
                str(item).strip()
                for item in (delivery.get("checks") or [])
                if str(item).strip()
            ]
            valid_delivery = submitted and bool(delivery_summary)
            if not valid_delivery:
                snapshot = persist_partial_snapshot()
            elif runtime is None:
                raise RuntimeError("Managed runtime missing")
            else:
                snapshot = runtime.snapshot_and_export(delivery_id, host_workdir)
            usage_raw = result.get("usage") or {}
            usage = {
                "input_tokens": int(usage_raw.get("input_tokens") or 0),
                "output_tokens": int(usage_raw.get("output_tokens") or 0),
                "cache_read_tokens": int(usage_raw.get("cache_read_tokens") or 0),
                "cache_write_tokens": int(usage_raw.get("cache_write_tokens") or 0),
                "llm_calls": int(usage_raw.get("llm_calls") or 0),
                "cost": float(usage_raw.get("cost") or 0),
                "latency_s": elapsed,
                "provider_model": (
                    (result.get("final_message") or {}).get("model")
                    or effective.get("model")
                ),
                "provider_fingerprint": None,
                "effective_seed": effective.get("seed"),
            }
            final_text = str(result.get("final_text") or "")
            action = {
                "delivery_session_id": delivery_id,
                "backend": result.get("backend", "pi-coding-agent"),
                "backend_version": result.get("backend_version"),
                "action_type": "pi_session",
                "done": valid_delivery,
                "raw_text": final_text,
                "raw_message": result.get("final_message"),
                "message": delivery_summary,
                "delivery_submission": {
                    "summary": delivery_summary,
                    "checks": delivery_checks,
                },
                "thought": (result.get("final_message") or {}).get("thinking", ""),
                "usage": usage,
                "tool_events": result.get("tool_events") or [],
                "tool_call_count": int(result.get("tool_call_count") or 0),
                "pi_turn_count": int(result.get("turn_count") or 0),
                "pi_turns": result.get("turns") or [],
                "pi_event_trace": result.get("event_trace") or [],
                "pi_messages": result.get("messages") or [],
                "model_trace": {
                    "trace_id": str(uuid4()),
                    "schema_version": 1,
                    "backend": result.get("backend", "pi-coding-agent"),
                    "backend_version": result.get("backend_version"),
                    "request_settings": result.get("request_settings", []),
                    "request": {
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "user_payload": json.loads(user_prompt),
                        "prompt_images": [],
                        "tool_permissions": ["read", "bash", "edit", "write", "submit_delivery"],
                    },
                    "final_text": final_text,
                    "final_message": result.get("final_message") or {},
                    "messages": result.get("messages") or [],
                    "turns": result.get("turns") or [],
                    "event_trace": result.get("event_trace") or [],
                    "tool_events": result.get("tool_events") or [],
                    "tool_call_count": int(result.get("tool_call_count") or 0),
                    "turn_count": int(result.get("turn_count") or 0),
                    "usage": usage,
                    "latency_s": elapsed,
                },
                "file_changes": snapshot,
            }
            if not valid_delivery:
                if stop_reason == "length":
                    code = "coding.output_limit"
                    message = "Model response reached its output limit without submitting a delivery"
                else:
                    code = "coding.missing_delivery"
                    message = "Model ended without a valid submit_delivery call"
                live.update(status="failed_terminal", updated_at=now_iso(), last_event=code)
                self._runtime_persist_pi_live(session["session_id"], live)
                raise CandidateCodingFailure(
                    code, message,
                    {"failure_kind": "candidate_protocol", "coding_action": action},
                )
            return action

        return run

    def _runtime_coding_evaluator(self, 
        task_id: str,
        runtime_spec=None,
    ):
        """Build the managed-runtime Coding evaluator."""
        if runtime_spec is None:
            raise ValueError("A managed task runtime is required")

        def run(context: dict) -> dict:
            session = context["session"]
            coding = session.get("branches", {}).get("coding") or {}
            delivery_id = (
                coding.get("delivery_session_id")
                or f"{session['session_id']}-coding"
            )
            actions = coding.get("actions", [])
            final_note = next(
                (
                    action.get("message", "")
                    for action in reversed(actions)
                    if action.get("done")
                ),
                "",
            )
            usage = {
                "input_tokens": sum(
                    (action.get("usage") or {}).get("input_tokens", 0)
                    for action in actions
                ),
                "output_tokens": sum(
                    (action.get("usage") or {}).get("output_tokens", 0)
                    for action in actions
                ),
                "llm_calls": sum((action.get("usage") or {}).get("llm_calls", 0) for action in actions),
                "latency_s": round(
                    sum(
                        (action.get("usage") or {}).get("latency_s", 0)
                        for action in actions
                    ),
                    2,
                ),
            }
            if runtime_spec is not None:
                runtime = self._runtime_official_runtime(runtime_spec)
                host_workdir = self.workdirs_dir / delivery_id
                bundle_dir = self._runtime_task_bundle(task_id)
                try:
                    runtime.prepare(delivery_id, host_workdir)
                    official = runtime.run_verifier(
                        delivery_id, host_workdir, bundle_dir
                    )
                    raw_results = official.get("test_results") or {}
                    raw_gates = official.get("gates") or {}
                    gate_mapping = runtime_spec.verifier.gate_mapping
                    # ``gate_mapping`` is intentionally slot-oriented (S01-S13),
                    # while the manifest also contains integration/basic tests.
                    # Keep those official gate records in the scorer input too;
                    # otherwise a normally completed verifier is misreported as
                    # ``evaluator.incomplete`` merely because the result adapter
                    # dropped two categories.
                    expected_ids = list(runtime_spec.verifier.expected_gate_ids)
                    result_ids = list(gate_mapping)
                    try:
                        manifest_ids = {
                            item.id
                            for item in manifest_from_registry(load_registry(bundle_dir)).tests
                        }
                    except Exception:
                        manifest_ids = set()
                    if expected_ids and set(expected_ids).issubset(manifest_ids):
                        result_ids.extend(
                            test_id for test_id in expected_ids
                            if test_id not in result_ids
                        )
                    test_results = {
                        test_id: (
                            raw_results.get(test_id)
                            or self._runtime_official_gate_result(raw_gates.get(test_id))
                            or {
                                "passed": False,
                                "skipped": False,
                                "detail": (
                                    "official runtime omitted a gate-mapped V4 "
                                    "test result"
                                ),
                            }
                        )
                        for test_id in result_ids
                    }
                    return {
                        "delivery_session_id": delivery_id,
                        "delivery_note": final_note,
                        "test_results": test_results,
                        "official_reward": official.get("reward"),
                        "official_gates": official.get("gates"),
                        "official_expected_gate_ids": list(
                            runtime_spec.verifier.expected_gate_ids
                        ),
                        "official_verifier": {
                            "ran": bool(official.get("ran")),
                            "returncode": official.get("returncode"),
                            "timed_out": bool(official.get("timed_out")),
                            "output": str(official.get("output") or ""),
                            "evidence": official.get("evidence"),
                        },
                        "runtime_provenance": runtime_spec.provenance(),
                        "snapshot": official.get("snapshot"),
                        "usage": usage,
                    }
                except Exception as error:
                    evidence = getattr(error, "verifier_evidence", None)
                    if evidence is not None:
                        raise RuntimeError(
                            str(error) + "\nVerifier evidence: " + json.dumps(evidence, sort_keys=True)
                        ) from error
                    raise
                finally:
                    runtime.cleanup(delivery_id)


        return run
