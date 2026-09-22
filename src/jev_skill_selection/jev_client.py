"""Minimal TypeSafe System One (Jev) HTTP client using stdlib urllib.

Official docs: https://docs.typesafe.ai
Endpoint: POST {base}/v1/systemone
Auth: Authorization: Bearer $TYPESAFE_API_KEY
Env (from TypeSafe Python SDK constants):
  TYPESAFE_API_KEY, TYPESAFE_BASE_URL, TYPESAFE_DEFAULT_MODEL

Request shape::

    {
      "model": "jev-1.13.0",
      "state": <str | object | array>,
      "questions": {
        "<id>": {
          "type": "noul" | "choice" | "score",
          "instructions": <str | object | array>,
          "criteria": ...  # optional for noul; required for choice/score
        }
      }
    }

Response shape::

    {
      "model": "jev-1.13.0",
      "answers": { "<id>": { "type": "...", ... } },
      "usage": { "input_tokens": N, "output_tokens": N }
    }

Default model pin ``jev-1.13.0`` — verify against docs/models; aliases like
``jev-latest`` move over time.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
DEFAULT_MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
# Pinned for reproducibility; check https://docs.typesafe.ai/models.md to verify.
DEFAULT_MODEL = "jev-1.13.0"


class JevError(Exception):
    """Base error for the Jev client."""


class JevConfigError(JevError):
    """Missing API key or invalid client configuration."""


class JevAPIError(JevError):
    """Non-2xx or malformed response from the TypeSafe API."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class SystemOneResult:
    model: str
    answers: dict[str, Any]
    usage: dict[str, Any]
    raw: dict[str, Any]


class JevClient:
    """Thin sync client for ``POST /v1/systemone``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        opener: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
        self.base_url = (
            (base_url if base_url is not None else os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL))
            .rstrip("/")
        )
        env_model = os.environ.get(DEFAULT_MODEL_ENV)
        self.model = model or env_model or DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        # Injectable for unit tests (callable(url, data, headers, timeout) -> bytes).
        self._opener = opener

    def require_api_key(self) -> None:
        if not self.api_key:
            raise JevConfigError(
                f"Missing TypeSafe API key. Set {API_KEY_ENV} or pass api_key=... "
                f"(see https://docs.typesafe.ai)."
            )

    def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
        model: str | None = None,
    ) -> SystemOneResult:
        """Evaluate ``state`` against typed ``questions``."""
        self.require_api_key()
        if not questions:
            raise JevConfigError("questions must be a non-empty map")

        payload = {
            "model": model or self.model,
            "state": state,
            "questions": dict(questions),
        }
        url = f"{self.base_url}/v1/systemone"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "jev-skill-selection/0.1.0",
        }

        raw_bytes = self._post(url, body, headers)
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JevAPIError(
                f"Invalid JSON from TypeSafe API: {exc}",
                body=raw_bytes.decode("utf-8", errors="replace"),
            ) from exc

        if not isinstance(data, dict) or "answers" not in data:
            raise JevAPIError("Unexpected response shape (missing answers)", body=str(data))

        return SystemOneResult(
            model=str(data.get("model") or payload["model"]),
            answers=dict(data.get("answers") or {}),
            usage=dict(data.get("usage") or {}),
            raw=data,
        )

    def _post(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        if self._opener is not None:
            return self._opener(url, body, headers, self.timeout_seconds)

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise JevAPIError(
                f"TypeSafe API HTTP {exc.code}: {err_body[:500]}",
                status=exc.code,
                body=err_body,
            ) from exc
        except urllib.error.URLError as exc:
            raise JevAPIError(f"TypeSafe API connection error: {exc.reason}") from exc
