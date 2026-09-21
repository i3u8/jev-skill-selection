"""Hermes plugin: register pre_llm_call → soft context via before_first_message.

Install by copying/symlinking this directory to ~/.hermes/plugins/jev-skill-selection/
(or HERMES_HOME/plugins/…). Hermes loads plugin.yaml and calls register(ctx).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from jev_skill_selection.adapters.common import (  # noqa: E402
    build_soft_context,
    options_from_env,
    run_selection,
)


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
                # OpenAI-style content parts
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
    return str(payload)


def on_pre_llm_call(payload: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Hermes hook: return ``{"context": "..."}`` for soft inject."""
    message = _extract_message(payload if payload is not None else kwargs)
    if not message.strip():
        return {}
    try:
        outcome = run_selection(message, host="hermes", options=options_from_env())
        return {"context": build_soft_context(outcome)}
    except Exception as exc:  # noqa: BLE001
        return {"context": f"jev-skill-selection hermes plugin error: {exc}"}


def register(ctx: Any) -> None:
    """Called by Hermes when the plugin loads."""
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):
        register_hook("pre_llm_call", on_pre_llm_call)
        return
    # Fallback attribute used by some plugin loaders
    hooks = getattr(ctx, "hooks", None)
    if isinstance(hooks, dict):
        hooks["pre_llm_call"] = on_pre_llm_call


# Re-export for harness smoke tests without a live Hermes runtime.
__all__ = ["register", "on_pre_llm_call"]
