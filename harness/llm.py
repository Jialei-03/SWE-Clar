"""LLM client supporting OpenAI-compatible and Anthropic-compatible chat APIs.

Each role has an independent RoleConfig,
allowing candidate and simulation roles to use different providers.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import httpx
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass
class RoleConfig:
    api_style: str = "openai"  # "openai" | "anthropic"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 1.0
    top_p: float | None = None   # None omits the field; use the server default
    max_tokens: int | None = None
    # Provider-dependent reasoning configuration
    thinking: str = "max"
    pi_profile: dict = field(default_factory=dict)
    extra_headers: dict = field(default_factory=dict)
    seed: int | None = None
    api_key_env: str = ""
    extra_header_envs: dict = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: object) -> "RoleConfig":
        document = getattr(profile, "document", profile)
        if not isinstance(document, Mapping):
            raise TypeError("profile must expose a configuration mapping")
        nested_sampling = document.get("sampling")
        sampling = nested_sampling if isinstance(nested_sampling, Mapping) else document
        return cls(
            api_style=document.get("api_style", "openai"),
            base_url=document.get("base_url", ""),
            model=document.get("model", ""),
            temperature=sampling.get("temperature", 1.0),
            top_p=sampling.get("top_p"),
            max_tokens=sampling.get("model_max_output_tokens"),
            pi_profile=dict(document.get("pi_profile", {})),
            thinking=document.get("thinking", "max"),
            seed=document.get("requested_seed"),
            api_key_env=document.get("api_key_env", ""),
            extra_header_envs=dict(document.get("extra_header_envs", {})),
        )

    def resolved_for_call(self, environ: Mapping[str, str] | None = None) -> "RoleConfig":
        environment = os.environ if environ is None else environ
        api_key = self.api_key
        if not api_key and self.api_key_env:
            api_key = environment.get(self.api_key_env, "")
            if not api_key:
                raise LLMError(
                    f"credential environment variable is not set: {self.api_key_env}"
                )
        headers = dict(self.extra_headers)
        for header, env_name in self.extra_header_envs.items():
            value = environment.get(env_name, "")
            if not value:
                raise LLMError(
                    f"credential environment variable is not set: {env_name}"
                )
            headers[header] = value
        return replace(self, api_key=api_key, extra_headers=headers)

    def masked(self) -> dict:
        d = {
            "api_style": self.api_style,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "thinking": self.thinking,
            "seed": self.seed,
            "api_key_env": self.api_key_env,
            "extra_header_envs": dict(self.extra_header_envs),
        }
        if self.api_key:
            d["api_key_masked"] = ""
            d["api_key_set"] = True
        else:
            d["api_key_masked"] = ""
            d["api_key_set"] = False
        return d


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    usage: dict          # {"input_tokens": int, "output_tokens": int} when reported
    latency_s: float
    raw_stop_reason: str = ""
    # Preserve raw assistant messages including reasoning_content/
    # reasoning_details in tool history.
    # Do not discard provider-required fields.
    raw_message: dict | None = None
    provider_model: str | None = None
    provider_fingerprint: str | None = None
    effective_seed: int | None = None


def _post_json(url: str, headers: dict, body: dict, timeout: int = 300) -> dict:
    try:
        with httpx.stream("POST", url, headers=headers, json=body, timeout=timeout, verify=ssl.create_default_context()) as resp:
            if resp.status_code >= 400:
                detail = resp.read().decode("utf-8", errors="replace")[:2000]
                if resp.status_code == 400 and not body.get("stream") and url.endswith("/chat/completions"):
                    try:
                        error = json.loads(detail).get("error", {})
                    except (ValueError, AttributeError):
                        error = {}
                    if isinstance(error, dict) and error.get("code") == "streaming_required":
                        return _post_json(url, headers, {**body, "stream": True}, timeout)
                detail = _redact_header_values(detail, headers)
                raise LLMError(f"HTTP {resp.status_code} from {url}: {detail}")
            if body.get("stream"):
                return _read_chat_stream(resp.iter_lines())
            return json.loads(resp.read().decode("utf-8"))
    except httpx.HTTPError as e:
        reason = _redact_header_values(str(e), headers)
        raise LLMError(f"Network error accessing {url}: {reason}") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LLMError("provider returned invalid JSON") from None


def _read_chat_stream(response) -> dict:
    result = {}
    content, reasoning = [], []
    finish = None
    done = False
    for raw_line in response:
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            done = True
            break
        chunk = json.loads(data)
        if not isinstance(chunk, dict) or chunk.get("error"):
            raise LLMError("provider returned a stream error")
        for key in ("model", "system_fingerprint", "usage"):
            if chunk.get(key) is not None:
                result[key] = chunk[key]
        for choice in chunk.get("choices", []):
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if delta.get("tool_calls"):
                raise LLMError("tool-call streams are not supported by the auxiliary chat client")
            content.append(delta.get("content") or "")
            reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
    if not done or finish is None:
        raise LLMError("provider stream ended before completion")
    message = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    result["choices"] = [{"message": message, "finish_reason": finish}]
    return result


def _redact_header_values(text: str, headers: dict) -> str:
    candidates: set[str] = set()
    for raw_value in headers.values():
        value = str(raw_value)
        if value:
            candidates.add(value)
            if " " in value:
                candidates.add(value.rsplit(" ", 1)[-1])
    for candidate in sorted(candidates, key=len, reverse=True):
        text = text.replace(candidate, "[REDACTED]")
    return text


def chat(cfg: RoleConfig, system: str, messages: list[dict],
         max_retries: int = 5, *, read_roots: list[dict[str,Any]] | None = None) -> LLMResult:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]

    Adapt formats to cfg.api_style; back off on retryable errors.
    """
    if cfg.api_style == 'pi':
        from runtime.pi_adapters import _run_pi_text
        started=time.monotonic()
        trace=_run_pi_text(cfg.pi_profile,system_prompt=system,
                           user_payload={'messages':messages},
                           read_roots=read_roots,
                           session_kind='private_review' if read_roots else 'text')
        return LLMResult(text=trace.get('final_text',''),usage=trace.get('usage',{}),
                         latency_s=time.monotonic()-started,raw_stop_reason=(trace.get('final_message') or {}).get('stop_reason',''),
                         raw_message={**(trace.get('final_message') or {}),'content':trace.get('final_text',''),'request_settings':trace.get('request_settings',[]),
                                      **({'private_tool_trace':trace} if read_roots else {})},
                         provider_model=cfg.model)
    if read_roots:
        raise LLMError('Private acceptance-source reading requires the Pi read-only transport; refusing silent fallback')
    cfg = cfg.resolved_for_call()
    if not cfg.base_url or not cfg.api_key or not cfg.model:
        raise LLMError("Incomplete LLM configuration: base_url, api_key and model are required")

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return _chat_once(cfg, system, messages)
        except LLMError as e:
            last_err = e
            msg = str(e)
            retryable = any(t in msg for t in ("HTTP 429", "HTTP 5", "Network error"))
            if attempt < max_retries and retryable:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise LLMError(str(last_err))


def _chat_once(cfg: RoleConfig, system: str, messages: list[dict]) -> LLMResult:
    t0 = time.time()
    if cfg.api_style == "anthropic":
        if cfg.max_tokens is None:
            raise LLMError("Anthropic requires model_max_output_tokens set to its supported output capacity")
        url = cfg.base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            **cfg.extra_headers,
        }
        body = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "system": system,
            "messages": messages,
        }
        if cfg.max_tokens is None:
            body.pop("max_tokens", None)
        if cfg.top_p is not None:
            body["top_p"] = cfg.top_p
        resp = _post_json(url, headers, body)
        # Some providers report errors in base_resp despite HTTP success
        base_resp = resp.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            detail = _redact_header_values(str(base_resp), headers)
            raise LLMError(f"Upstream error base_resp={detail}")
        blocks = resp.get("content") or []
        text = "".join(
            b.get("text", "") for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        usage_raw = resp.get("usage") or {}
        usage = {
            "input_tokens": usage_raw.get("input_tokens", 0),
            "output_tokens": usage_raw.get("output_tokens", 0),
        }
        stop = resp.get("stop_reason") or ""
        raw_message = {"role": "assistant", "content": resp.get("content")}
    else:  # OpenAI-compatible
        url = cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg.api_key}", **cfg.extra_headers}
        oai_messages = [{"role": "system", "content": system}] + messages
        body = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": oai_messages,
        }
        if cfg.max_tokens is None:
            body.pop("max_tokens", None)
        if cfg.top_p is not None:
            body["top_p"] = cfg.top_p
        if cfg.seed is not None:
            body["seed"] = cfg.seed
        if "minimax" in cfg.base_url.lower():
            # Keep reasoning in a separate field,
            # with tag stripping below as a fallback.
            body["reasoning_split"] = True
            # Use the supported completion-token parameter
            
            if "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
            if cfg.thinking in ("adaptive", "disabled"):
                body["thinking"] = {"type": cfg.thinking}
        resp = _post_json(url, headers, body)
        base_resp = resp.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            detail = _redact_header_values(str(base_resp), headers)
            raise LLMError(f"Upstream error base_resp={detail}")
        choices = resp.get("choices") or []
        if not choices:
            raise LLMError("Response has no choices")
        msg = choices[0].get("message") or {}
        stop = choices[0].get("finish_reason") or ""
        raw_message = msg  # Preserve reasoning_content/reasoning_details
        text = msg.get("content") or ""
        # Remove inline reasoning tags,
        # including unclosed truncated blocks,
        # so reasoning is not scored as an answer.
        text = re.sub(r"<think>.*?(?:</think>|\Z)", "", text, flags=re.DOTALL)
        # Remove provider delimiter artifacts.
        # Do not alter substantive response text.
        text = re.sub(r"\[e~\[|\]<\]minimax\[>\[", "", text)
        # Some models put text in reasoning; truncated reasoning
        # must not substitute for an answer.
        if not text.strip() and msg.get("reasoning_content") and stop != "length":
            text = msg["reasoning_content"]
        if not text.strip() and stop == "length":
            raise LLMError(
                "Output truncated at max_tokens with no answer text. "
                "Review the role token limit before retrying."
            )
        usage_raw = resp.get("usage") or {}
        usage = {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
        }

    if not text.strip():
        raise LLMError("Model returned empty content")
    provider_model = resp.get("model")
    provider_fingerprint = (
        resp.get("system_fingerprint")
        or resp.get("provider_fingerprint")
        or resp.get("fingerprint")
    )
    confirmed_seed = resp.get("effective_seed", resp.get("seed"))
    effective_seed = (
        confirmed_seed
        if isinstance(confirmed_seed, int) and not isinstance(confirmed_seed, bool)
        else None
    )
    return LLMResult(
        text=text.strip(),
        usage=usage,
        latency_s=round(time.time() - t0, 2),
        raw_stop_reason=stop,
        raw_message=raw_message,
        provider_model=provider_model if isinstance(provider_model, str) else None,
        provider_fingerprint=(
            provider_fingerprint if isinstance(provider_fingerprint, str) else None
        ),
        effective_seed=effective_seed,
    )


def extract_json(text: str, *, expected_type: type | None = None):
    """Extract the first JSON object or array, allowing Markdown fences."""
    text = text.strip()
    # Hosted supervisors may put explanatory prose before one explicit JSON
    # answer. Brackets in that prose are not the response envelope. Only accept
    # one complete terminal fence; do not scan arbitrary nested JSON fragments.
    import re
    fences = list(re.finditer(r"```json\s*\n([\s\S]*?)```", text, re.IGNORECASE))
    if fences and not text.startswith("```"):
        parse_error = ValueError if expected_type is not None else LLMError
        if len(fences) != 1 or text[fences[0].end():].strip():
            raise parse_error("Ambiguous JSON output: expected one terminal JSON fence")
        prefix = text[:fences[0].start()].lstrip()
        if prefix.startswith(("{", "[")):
            raise parse_error("Invalid JSON envelope before fenced response")
        try:
            value = json.loads(fences[0].group(1))
        except json.JSONDecodeError as error:
            raise parse_error(f"Invalid or incomplete fenced JSON output: {error}") from error
        if expected_type is not None and not isinstance(value, expected_type):
            raise ValueError(f"JSON output must be {expected_type.__name__}, got {type(value).__name__}")
        return value
    if text.startswith("```"):
        # Remove Markdown JSON fences
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    parse_error = ValueError if expected_type is not None else LLMError
    # Parse only the first top-level value. Never salvage a nested array or
    # object from a truncated envelope and silently change the response type.
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        starts = [index for char in ("{", "[") if (index := text.find(char)) >= 0]
        if not starts:
            raise parse_error("Invalid JSON output: no top-level object or array") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(text[min(starts):])
        except json.JSONDecodeError as error:
            raise parse_error(f"Invalid or incomplete JSON output: {error}") from error
    if expected_type is not None and not isinstance(value, expected_type):
        raise ValueError(f"JSON output must be {expected_type.__name__}, got {type(value).__name__}")
    return value
