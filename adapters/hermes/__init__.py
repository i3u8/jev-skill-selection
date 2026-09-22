"""Hermes plugin: hard-filter skills via llm_request middleware (default).

Default path: ``register_middleware("llm_request", ...)`` rewrites provider
kwargs so dropped skills are stripped from ``<available_skills>`` blocks before
the request is sent. Soft ``pre_llm_call`` context only when
``JEV_FILTER_MODE=soft`` or ``both``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from jev_skill_selection.adapters.common import (  # noqa: E402
    build_soft_context,
    e2e_log_selection,
    filter_hermes_llm_request,
    filter_mode_from_env,
    options_from_env,
    run_selection,
    wants_hard,
    wants_soft,
)

_LAST: dict[str, Any] = {
    "kept_names": [],
    "dropped_names": [],
    "message": "",
    "outcome": None,
}


def _extract_message(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("message", "user_message", "prompt", "text", "content"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                if parts:
                    return "\n".join(parts)
        msgs = payload.get("messages")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("role") == "user":
                    return _extract_message(m)
        req = payload.get("request")
        if isinstance(req, dict) and req is not payload:
            return _extract_message(req)
    return str(payload) if not isinstance(payload, dict) else ""


def _extract_message_from_request(request: Any) -> str:
    if not isinstance(request, dict):
        return ""
    for key in ("messages", "input"):
        msgs = request.get(key)
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("role") == "user":
                    return _extract_message(m)
                if isinstance(m, str) and m.strip():
                    return m
                if isinstance(m, dict) and m.get("type") == "message" and m.get("role") == "user":
                    return _extract_message(m)
    return ""


def _run_and_store(message: str) -> None:
    if not message.strip():
        return
    try:
        outcome = run_selection(message, host="hermes", options=options_from_env())
        _LAST["kept_names"] = list(outcome.result.kept_names)
        _LAST["dropped_names"] = list(outcome.result.dropped_names)
        _LAST["message"] = message
        _LAST["outcome"] = outcome
    except Exception:  # noqa: BLE001
        pass


def on_pre_llm_call(payload: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Optional soft path: return ``{"context": "..."}`` when soft/both."""
    mode = filter_mode_from_env()
    message = _extract_message(payload if payload is not None else kwargs)
    if message.strip():
        _run_and_store(message)

    if not wants_soft(mode):
        return {}

    outcome = _LAST.get("outcome")
    if outcome is None:
        return {}
    try:
        ctx = build_soft_context(outcome)
        e2e_log_selection(
            host="hermes",
            message=message or _LAST.get("message", ""),
            outcome=outcome,
            soft_context=ctx,
            filter_mode=mode,
            hard_applied=False,
        )
        return {"context": ctx}
    except Exception as exc:  # noqa: BLE001
        return {"context": f"jev-skill-selection hermes plugin error: {exc}"}


def on_llm_request(**kwargs: Any) -> dict[str, Any] | None:
    """Hard path: strip dropped skills from ``<available_skills>`` in the request."""
    mode = filter_mode_from_env()
    if not wants_hard(mode):
        return None

    request = kwargs.get("request")
    if not isinstance(request, dict):
        return None

    message = _extract_message_from_request(request) or _LAST.get("message", "")
    if message.strip() and (
        (not _LAST.get("kept_names") and not _LAST.get("dropped_names"))
        or message != _LAST.get("message")
    ):
        _run_and_store(message)

    kept = list(_LAST.get("kept_names") or [])
    if not kept and not _LAST.get("dropped_names"):
        return None

    filtered = filter_hermes_llm_request(request, kept)
    outcome = _LAST.get("outcome")
    if outcome is not None:
        e2e_log_selection(
            host="hermes",
            message=_LAST.get("message", ""),
            outcome=outcome,
            soft_context=None,
            filter_mode=mode,
            hard_applied=True,
        )
    return {
        "request": filtered,
        "source": "jev-skill-selection",
        "reason": "hard-filter available_skills to kept names",
    }


def register(ctx: Any) -> None:
    """Called by Hermes when the plugin loads."""
    register_hook = getattr(ctx, "register_hook", None)
    register_middleware = getattr(ctx, "register_middleware", None)

    if callable(register_middleware):
        register_middleware("llm_request", on_llm_request)

    if callable(register_hook):
        register_hook("pre_llm_call", on_pre_llm_call)
        return

    hooks = getattr(ctx, "hooks", None)
    if isinstance(hooks, dict):
        hooks["pre_llm_call"] = on_pre_llm_call

    mw = getattr(ctx, "middleware", None)
    if isinstance(mw, dict):
        mw["llm_request"] = on_llm_request


__all__ = ["register", "on_pre_llm_call", "on_llm_request"]
