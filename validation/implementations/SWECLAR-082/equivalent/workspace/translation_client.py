"""HTTP adapter for the configured local translation provider."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen
from typing import Any


class TranslationClient:
    """POST translation requests and validate the provider response."""

    def __init__(self, url: str, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout

    def translate(self, text: str, language: str) -> str:
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("translation provider is not configured")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("source text is blank")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language is blank")

        payload = json.dumps(
            {"text": text, "language": language},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.getcode()
                body = response.read()
        except Exception as exc:
            # The session boundary deliberately treats all provider/network
            # failures as a failed translation and never writes a cache entry.
            raise RuntimeError("translation provider request failed") from exc

        if not isinstance(status, int) or not 200 <= status < 300:
            raise RuntimeError("translation provider returned a non-2xx status")
        try:
            result: Any = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("translation provider returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("translation provider returned invalid JSON")
        if result.get("source_text") != text or result.get("language") != language:
            raise RuntimeError("translation provider response mismatch")
        translated = result.get("translated_text")
        if not isinstance(translated, str) or not translated.strip():
            raise RuntimeError("translation provider returned empty text")
        return translated
