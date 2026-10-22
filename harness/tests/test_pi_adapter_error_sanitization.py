"""Regression tests for safe propagation of structured transport failures."""

import json

from runtime.pi_adapters import _safe_runner_error


def test_safe_runner_error_keeps_structured_provider_fields_only():
    provider_error = json.dumps(
        {
            "error": {
                "message": "PRIVATE PROMPT BODY",
                "type": "invalid_request_error",
                "code": "unsupported_parameter",
                "param": "stream_options",
            }
        }
    )

    detail = _safe_runner_error(
        "exit_code=1",
        "400 Sol transport: HTTPError",
        provider_error,
        "transport=chars:82,lf:1,unicode_separators:0,markers:1",
    )

    assert "exit_code=1" in detail
    assert "http=400" in detail
    assert "upstream_error_code=unsupported_parameter" in detail
    assert "upstream_error_type=invalid_request_error" in detail
    assert "upstream_error_param=stream_options" in detail
    assert "PRIVATE" not in detail
    assert "message" not in detail


def test_safe_runner_error_does_not_stringify_secret_mapping_values():
    detail = _safe_runner_error(
        {
            "error": {
                "message": "PRIVATE PROMPT BODY",
                "api_key": "PRIVATE KEY",
                "code": "invalid_request",
            }
        }
    )

    assert detail == "upstream_error_code=invalid_request"
    assert "PRIVATE" not in detail


def test_safe_runner_error_preserves_structured_http_status_forms():
    assert _safe_runner_error("400 Sol transport: HTTPError") == (
        "http=400 | transport_error_type=HTTPError"
    )
    assert _safe_runner_error("bridge code=upstream_http_400") == "http=400"
