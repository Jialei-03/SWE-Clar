"""Pi-backed adapters for every model-under-test interaction.

Client simulation and disclosure supervision remain fixed benchmark
infrastructure. One accepted ``message_client`` call is one natural Client turn;
no second model rewrites or splits the Coding Agent's message. The Candidate, Audit,
and Coding branches use the
same Pi model profile so a model comparison does not silently swap the
clarification policy while keeping only the implementation model different.
"""

from __future__ import annotations
from uuid import uuid4

import prompts

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from llm import LLMError

from .role_adapters import _AUDIT_RESPONSE_SCHEMA


_RUNNER = Path(__file__).resolve().parent.parent / "pi" / "runner.mjs"
_PI_RESULT_START = re.compile(r'\{\s*"kind"\s*:\s*"pi_result"')
_SAFE_ERROR_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\[\]-]{0,127}$")


def _extract_pi_result(stdout: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Extract the final Pi result without corrupting valid JSON text.

    ``str.splitlines()`` is intentionally not used here.  Python treats NEL,
    U+2028, and U+2029 as line boundaries, while JSON permits those Unicode
    characters inside strings and Node's ``JSON.stringify`` may emit them
    literally.  Splitting on them turns one valid NDJSON envelope into several
    invalid fragments.  The Pi protocol itself is delimited only by ASCII LF.

    A raw-decoder fallback also tolerates an SDK writing harmless diagnostic
    text immediately before the final envelope.  It never accepts an object
    unless that object is explicitly tagged ``kind=pi_result``.
    """

    diagnostics: dict[str, Any] = {
        "stdout_chars": len(stdout),
        "ascii_lf_count": stdout.count("\n"),
        "unicode_line_separator_count": sum(
            stdout.count(char) for char in ("\u0085", "\u2028", "\u2029")
        ),
        "result_marker_count": len(_PI_RESULT_START.findall(stdout)),
        "recovered": False,
        "recovery_reason": None,
    }

    # NDJSON is delimited by one literal ASCII LF.  Do not use splitlines().
    for line in stdout.split("\n"):
        if not line.strip():
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("kind") == "pi_result":
            result = candidate.get("result")
            if isinstance(result, dict):
                if diagnostics["unicode_line_separator_count"]:
                    diagnostics["recovered"] = True
                    diagnostics["recovery_reason"] = "unicode_line_separator"
                return result, diagnostics

    # Some provider SDKs may write a warning without a terminating LF.  Scan
    # only explicit pi_result markers and decode the tagged object in place.
    decoder = json.JSONDecoder()
    matches = list(_PI_RESULT_START.finditer(stdout))
    for match in reversed(matches):
        try:
            candidate, _end = decoder.raw_decode(stdout[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("kind") == "pi_result":
            result = candidate.get("result")
            if isinstance(result, dict):
                diagnostics["recovered"] = True
                diagnostics["recovery_reason"] = "framing_noise"
                return result, diagnostics
    return None, diagnostics


def _safe_error_token(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_ERROR_TOKEN.fullmatch(value):
        return value
    return None


def _structured_error(value: object) -> dict[str, str]:
    """Extract provider error fields without retaining prose or payload data."""

    fields: dict[str, str] = {}
    mapping: Mapping[str, Any] | None = value if isinstance(value, Mapping) else None
    if mapping is not None and isinstance(mapping.get("error"), Mapping):
        mapping = mapping["error"]
    if mapping is not None:
        for source, target in (
            ("code", "upstream_error_code"),
            ("upstream_code", "upstream_error_code"),
            ("type", "upstream_error_type"),
            ("upstream_type", "upstream_error_type"),
            ("param", "upstream_error_param"),
            ("upstream_param", "upstream_error_param"),
        ):
            token = _safe_error_token(mapping.get(source))
            if token is not None and target not in fields:
                fields[target] = token
        return fields

    if not isinstance(value, str):
        return fields
    text = value
    if "HTTPError" in text:
        fields["transport_error_type"] = "HTTPError"
    status = re.search(r"\bHTTP(?:Error)?\s*([45]\d\d)\b", text)
    if status is None:
        # The loopback bridge's historical client-facing error is prefixed
        # with the status: ``400 Sol transport: HTTPError``.  Match that
        # exact safe framing, not arbitrary numbers in provider prose.
        status = re.search(r"\b([45]\d\d)\s+Sol transport:\s*HTTPError\b", text)
    if status is None:
        # New bridge responses carry a structured ``upstream_http_<status>``
        # code when the SDK stringifies the JSON error envelope.
        status = re.search(r"\bupstream_http_([45]\d\d)\b", text)
    if status:
        fields["http"] = status.group(1)
    exit_code = re.search(r"\bexit_code=(-?\d+)\b", text)
    if exit_code:
        fields["exit_code"] = exit_code.group(1)
    transport = re.search(
        r"\btransport=chars:\d+,lf:\d+,unicode_separators:\d+,markers:\d+\b", text
    )
    if transport:
        fields["transport"] = transport.group(0).removeprefix("transport=")

    # Some SDKs stringify the bridge's safe JSON error instead of preserving
    # the object. Decode only a tagged object and inspect structured fields;
    # never copy its message or any other string into the run error.
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            candidate, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        nested = _structured_error(candidate)
        for key, token in nested.items():
            fields.setdefault(key, token)
        if nested:
            break
    return fields


def _safe_runner_error(*values: object) -> str:
    """Return structured diagnostics without credentials, prompts, or bodies."""

    fields: dict[str, str] = {}
    for value in values:
        for key, token in _structured_error(value).items():
            fields.setdefault(key, token)
    if not fields:
        return "unknown runner failure"
    order = (
        "exit_code",
        "http",
        "transport_error_type",
        "upstream_error_code",
        "upstream_error_type",
        "upstream_error_param",
        "transport",
    )
    return " | ".join(f"{key}={fields[key]}" for key in order if key in fields)[:600]


def _public_model_config(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in profile.items()
        if key not in {"api_key", "auth_path", "profile_id", "label"}
    }


def _run_pi_text(
    profile: Mapping[str, Any],
    *,
    system_prompt: str,
    user_payload: Mapping[str, Any],
    read_roots: list[Mapping[str, Any]] | None = None,
    runtime_context: Mapping[str, Any] | None = None,
    session_kind: str = "text",
    # A target-model trajectory owns its stopping decision.  An optional
    # timeout remains available to focused diagnostics, but production Agent
    # and Audit turns do not turn long reasoning into a benchmark failure.
    timeout_s: int | None = None,
) -> dict[str, Any]:
    if not _RUNNER.is_file():
        raise LLMError(f"Pi runner is not installed: {_RUNNER}")
    auth_path = str(profile.get("auth_path") or "/tmp/sweclar-pi-auth.json")
    payload = {
        "session_kind": session_kind,
        "model_config": _public_model_config(profile),
        "system_prompt": system_prompt,
        "user_prompt": json.dumps(user_payload, ensure_ascii=False),
        "auth_path": auth_path,
        "agent_dir": str(Path(auth_path).parent),
        "stream_progress": False,
        "read_roots": [dict(item) for item in (read_roots or [])],
        "runtime_public_read_files": {item['virtual']:item['files'][''] for item in (read_roots or [])
                                      if item.get('public_environment') is True},
    }
    if runtime_context:
        for key in (
            "runtime_container",
            "runtime_workspace",
            "runtime_uid",
            "command_timeout_s",
        ):
            if runtime_context.get(key) is not None:
                payload[key] = runtime_context[key]
    environment = dict(os.environ)
    api_key = str(profile.get("api_key") or "")
    if not api_key and profile.get('api_key_env'):
        api_key = environment.get(str(profile['api_key_env']), '')
        if not api_key:
            raise LLMError('Selected Pi credential environment variable is not set')
    if api_key:
        environment["SWECLAR_PI_MODEL_API_KEY"] = api_key
    started = time.monotonic()
    try:
        completed = subprocess.run(
            ["node", str(_RUNNER)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LLMError("Pi target-model call timed out") from error

    result, transport = _extract_pi_result(completed.stdout)
    if isinstance(result, dict) and isinstance(result.get('refusal'), dict):
        refusal = result['refusal']
        category = _safe_error_token(refusal.get('category')) or 'unspecified'
        error = LLMError(f'provider_refusal category={category}')
        error.provider_refusal = True
        raise error
    if (
        completed.returncode != 0
        or not isinstance(result, dict)
        or result.get("ok") is not True
    ):
        result_error = result.get("error") if isinstance(result, dict) else None
        detail = _safe_runner_error(
            f"exit_code={completed.returncode}",
            result_error,
            (
                "transport="
                f"chars:{transport['stdout_chars']},"
                f"lf:{transport['ascii_lf_count']},"
                f"unicode_separators:{transport['unicode_line_separator_count']},"
                f"markers:{transport['result_marker_count']}"
            ),
            completed.stderr,
            completed.stdout[-1200:],
        )
        raise LLMError(f"Pi target-model call failed: {detail}")
    result["transport"] = transport
    result["latency_s"] = round(time.monotonic() - started, 3)
    return result


def _metadata(profile: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    final_message = result.get("final_message")
    final_message = final_message if isinstance(final_message, Mapping) else {}
    return {
        "backend": "pi-coding-agent",
        "provider": final_message.get("provider") or profile.get("provider"),
        "requested_model": profile.get("model"),
        "provider_model": final_message.get("model") or profile.get("model"),
        "provider_fingerprint": None,
        "effective_seed": None,
        "usage": result.get("usage") or {},
        "transport": result.get("transport") or {},
        "latency_s": result.get("latency_s"),
    }


def _observable_trace(
    result: Mapping[str, Any],
    *,
    system_prompt: str,
    user_payload: Mapping[str, Any],
    tool_permissions: list[str] | None = None,
) -> dict[str, Any]:
    """Return the complete provider-observable Pi trace without credentials.

    Text-mode Candidate and Audit calls intentionally have no tools.  Keeping
    the same transcript shape as Coding makes that absence explicit while
    preserving every message, provider-returned thinking field, lifecycle
    event, and usage record Pi actually returned.
    """

    user_prompt = json.dumps(user_payload, ensure_ascii=False)
    return {
        "schema_version": 1,
        "trace_id": str(uuid4()),
        "backend": result.get("backend") or "pi-coding-agent",
        "backend_version": result.get("backend_version"),
        "request_settings": result.get("request_settings", []),
        "request": {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "user_payload": dict(user_payload),
            "prompt_image_count": 0,
            "tool_permissions": list(tool_permissions or []),
        },
        "final_text": result.get("final_text") or "",
        "final_message": result.get("final_message") or {},
        "messages": result.get("messages") or [],
        "turns": result.get("turns") or [],
        "event_trace": result.get("event_trace") or [],
        "tool_events": result.get("tool_events") or [],
        "tool_call_count": int(result.get("tool_call_count") or 0),
        "turn_count": int(result.get("turn_count") or 0),
        "usage": result.get("usage") or {},
        "latency_s": result.get("latency_s"),
    }


class PiCandidateTurn:
    """Ask clarification questions through the selected Pi model profile."""

    def __init__(
        self,
        profile: Mapping[str, Any],
        *,
        read_roots: list[Mapping[str, str]] | None = None,
        runtime_provider: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        runtime_cleanup: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.profile = dict(profile)
        self.read_roots = [dict(item) for item in (read_roots or [])]
        self.runtime_provider = runtime_provider
        self.runtime_cleanup = runtime_cleanup
        self.calls: list[dict[str, Any]] = []
        self.last_response_text: str | None = None
        self.last_trace: dict[str, Any] | None = None
        self.last_workflow_action: dict[str, Any] | None = None

    def __call__(self, context: dict[str, Any]) -> str:
        system = prompts.CLARIFICATION_SYSTEM
        runtime_context = (
            dict(self.runtime_provider(context))
            if self.runtime_provider is not None
            else {}
        )
        try:
            result = _run_pi_text(
                self.profile,
                system_prompt=system,
                user_payload=context,
                read_roots=self.read_roots,
                runtime_context=runtime_context,
                session_kind="clarification",
            )
        finally:
            if self.runtime_cleanup is not None and runtime_context:
                self.runtime_cleanup(runtime_context)
        self.last_trace = _observable_trace(
            result,
            system_prompt=system,
            user_payload=context,
            tool_permissions=[
                "read",
                "message_client", "finish_clarification",
            ],
        )
        text = str(result.get("final_text") or "")
        self.last_response_text = text
        self.calls.append(_metadata(self.profile, result))
        workflow = result.get("workflow_action")
        self.last_workflow_action = (
            dict(workflow) if isinstance(workflow, dict) else None
        )
        if isinstance(workflow, dict) and workflow.get("action") == "message":
            message = workflow.get("message")
            if isinstance(message, str) and message.strip():
                projected = {"action": "message", "message": message.strip()}
                return json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        if isinstance(workflow, dict) and workflow.get("action") == "ready":
            projected = {"action": "ready"}
            reason = workflow.get("reason")
            if isinstance(reason, str) and reason.strip():
                projected["decision_summary"] = reason.strip()[:500]
            return json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        raise LLMError(
            "Pi Candidate must call message_client or finish_clarification"
        )


class PiAuditTurn:
    """Audit Requirement Units through the same model used for Coding."""

    def __init__(
        self,
        profile: Mapping[str, Any],
        *,
        read_roots: list[Mapping[str, str]] | None = None,
        runtime_provider: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        runtime_cleanup: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.profile = dict(profile)
        self.read_roots = [dict(item) for item in (read_roots or [])]
        self.runtime_provider = runtime_provider
        self.runtime_cleanup = runtime_cleanup
        self.calls: list[dict[str, Any]] = []
        self.last_response_text: str | None = None
        self.last_parsed: object | None = None
        self.last_trace: dict[str, Any] | None = None

    def __call__(self, context: dict[str, Any]) -> object:
        system = prompts.AUDIT_SYSTEM
        payload = dict(context)
        payload["response_schema"] = _AUDIT_RESPONSE_SCHEMA
        runtime_context = (
            dict(self.runtime_provider(context))
            if self.runtime_provider is not None
            else {}
        )
        try:
            result = _run_pi_text(
                self.profile,
                system_prompt=system,
                user_payload=payload,
                read_roots=self.read_roots,
                runtime_context=runtime_context,
                session_kind="audit",
            )
        finally:
            if self.runtime_cleanup is not None and runtime_context:
                self.runtime_cleanup(runtime_context)
        self.last_trace = _observable_trace(
            result,
            system_prompt=system,
            user_payload=payload,
            tool_permissions=[
                "read", "submit_audit_answers"
            ],
        )
        text = str(result.get("final_text") or "")
        self.last_response_text = text
        self.calls.append(_metadata(self.profile, result))
        workflow = result.get("workflow_action")
        if not isinstance(workflow, dict) or workflow.get("action") != "audit":
            raise LLMError("Pi Audit Agent must call submit_audit_answers")
        self.last_parsed = {"answers": workflow.get("answers") or []}
        return self.last_parsed
