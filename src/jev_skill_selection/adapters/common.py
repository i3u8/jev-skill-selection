"""Shared helpers for host hook/plugin adapters.

Soft-inject path: parse host stdin → :func:`~jev_skill_selection.hook.before_first_message`
→ emit host-shaped stdout (Claude/Codex ``UserPromptSubmit`` JSON, Hermes context dict, …).

Hard-filter (host-specific, optional phase-2) is documented per adapter README and is
*not* performed here — this module only produces keep/drop context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..hook import HookContext, HookOutcome, before_first_message
from ..models import SelectionOptions

# Soft-inject budget: Claude Code caps additionalContext ~10k chars.
_DEFAULT_CONTEXT_BUDGET = 9000


def default_skill_roots(host: str, *, home: Path | None = None, cwd: Path | None = None) -> list[Path]:
    """Return conventional skill directories for ``host``.

    Missing directories are still returned so callers can pass them to
    :func:`~jev_skill_selection.catalog.load_catalog` (which skips empties).
    """
    home = home or Path.home()
    cwd = cwd or Path.cwd()
    host = host.lower().replace("-", "_")

    if host in ("claude", "claude_code"):
        return [
            cwd / ".claude" / "skills",
            home / ".claude" / "skills",
        ]
    if host == "codex":
        return [
            cwd / ".agents" / "skills",
            home / ".agents" / "skills",
            home / ".codex" / "skills",
        ]
    if host == "hermes":
        hermes_home = Path(os.environ.get("HERMES_HOME", home / ".hermes"))
        return [
            hermes_home / "skills",
            cwd / ".hermes" / "skills",
        ]
    if host in ("opencode", "open_code"):
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        return [
            cwd / ".opencode" / "skills",
            xdg / "opencode" / "skills",
            # Compat paths (OpenCode can load Claude/Agents skills):
            cwd / ".claude" / "skills",
            home / ".claude" / "skills",
            cwd / ".agents" / "skills",
            home / ".agents" / "skills",
        ]
    raise ValueError(f"Unknown host: {host!r}")


def resolve_skill_roots(
    host: str,
    *,
    explicit: Sequence[str | Path] | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
) -> list[Path]:
    """Prefer ``JEV_SKILL_ROOTS`` (os.pathsep-separated), then ``explicit``, then defaults."""
    env = os.environ.get("JEV_SKILL_ROOTS", "").strip()
    if env:
        return [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    if explicit:
        return [Path(p).expanduser() for p in explicit]
    return default_skill_roots(host, home=home, cwd=cwd)


def options_from_env(defaults: SelectionOptions | None = None) -> SelectionOptions:
    """Build :class:`SelectionOptions` from env (defaults to local mode, no API key)."""
    base = defaults or SelectionOptions()
    mode = os.environ.get("JEV_MODE", base.mode).strip().lower() or base.mode
    if mode not in ("local", "jev"):
        mode = "local"
    threshold = float(os.environ.get("JEV_THRESHOLD", str(base.threshold)))
    max_keep_raw = os.environ.get("JEV_MAX_KEEP", "").strip()
    max_keep = int(max_keep_raw) if max_keep_raw else base.max_keep
    model = os.environ.get("JEV_MODEL", base.model)
    strategy = os.environ.get("JEV_STRATEGY", base.jev_strategy).strip().lower()
    if strategy not in ("noul", "choice"):
        strategy = base.jev_strategy
    return SelectionOptions(
        mode=mode,  # type: ignore[arg-type]
        threshold=threshold,
        max_keep=max_keep,
        always_keep=base.always_keep,
        always_drop=base.always_drop,
        model=model,
        jev_strategy=strategy,  # type: ignore[arg-type]
        local_prefilter=base.local_prefilter,
        local_prefilter_top_k=base.local_prefilter_top_k,
        body_excerpt_chars=base.body_excerpt_chars,
        api_key=base.api_key,
        base_url=base.base_url,
        timeout_seconds=base.timeout_seconds,
    )


def parse_user_prompt_submit(payload: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    """Normalize Claude/Codex ``UserPromptSubmit`` stdin JSON.

    Returns a dict with at least ``prompt`` (str) and the raw payload under ``raw``.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        text = payload.strip()
        data: Any = json.loads(text) if text else {}
    else:
        data = dict(payload)

    prompt = (
        data.get("prompt")
        or data.get("user_message")
        or data.get("message")
        or data.get("text")
        or ""
    )
    if not isinstance(prompt, str):
        prompt = str(prompt)
    return {
        "prompt": prompt,
        "cwd": data.get("cwd"),
        "session_id": data.get("session_id"),
        "hook_event_name": data.get("hook_event_name") or data.get("hookEventName"),
        "raw": data,
    }


def build_soft_context(
    outcome: HookOutcome,
    *,
    include_bodies: bool = True,
    budget: int | None = None,
) -> str:
    """Render keep/drop guidance (+ optional kept skill blocks) for soft inject."""
    limit = budget if budget is not None else int(
        os.environ.get("JEV_CONTEXT_BUDGET", str(_DEFAULT_CONTEXT_BUDGET))
    )
    result = outcome.result
    lines: list[str] = [
        "jev-skill-selection: pre-message keep/drop filter (soft inject).",
        "Prefer the kept skills below for this turn; treat dropped skills as out of scope.",
        f"mode={result.mode} kept={len(result.kept)} dropped={len(result.dropped)} "
        f"chars_saved={result.chars_saved}",
        "",
        "KEPT:",
    ]
    for d in result.kept:
        lines.append(f"  - {d.name} (score={d.score:.3f}): {d.reason}")
    lines.append("")
    lines.append("DROPPED:")
    for d in result.dropped:
        lines.append(f"  - {d.name} (score={d.score:.3f}): {d.reason}")

    header = "\n".join(lines)
    if not include_bodies or not outcome.prompt_blocks:
        return header[:limit]

    parts = [header, "", "KEPT_SKILL_CONTENT:"]
    used = len("\n".join(parts))
    for block in outcome.prompt_blocks:
        chunk = "\n\n" + block
        if used + len(chunk) > limit:
            remaining = limit - used - 80
            if remaining > 200:
                parts.append("\n\n" + block[:remaining] + "\n…[truncated]")
            else:
                parts.append("\n\n…[additional kept skill bodies omitted due to context budget]")
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)[:limit]


def emit_user_prompt_submit(
    context: str,
    *,
    hook_event_name: str = "UserPromptSubmit",
) -> dict[str, Any]:
    """Claude Code / Codex stdout shape for soft inject."""
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": context,
        }
    }


def run_selection(
    user_message: str,
    *,
    host: str,
    skill_roots: Sequence[str | Path] | None = None,
    options: SelectionOptions | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
) -> HookOutcome:
    """Resolve roots + options and run :func:`before_first_message`."""
    roots = resolve_skill_roots(host, explicit=skill_roots, home=home, cwd=cwd)
    opts = options or options_from_env()
    return before_first_message(
        HookContext(user_message=user_message, skill_roots=roots, options=opts)
    )


def handle_user_prompt_submit_stdin(
    stdin_text: str,
    *,
    host: str,
    skill_roots: Sequence[str | Path] | None = None,
    options: SelectionOptions | None = None,
) -> dict[str, Any]:
    """End-to-end: stdin JSON → selection → Claude/Codex stdout dict."""
    parsed = parse_user_prompt_submit(stdin_text)
    cwd = Path(parsed["cwd"]) if parsed.get("cwd") else None
    outcome = run_selection(
        parsed["prompt"],
        host=host,
        skill_roots=skill_roots,
        options=options,
        cwd=cwd,
    )
    event = parsed.get("hook_event_name") or "UserPromptSubmit"
    ctx = build_soft_context(outcome)
    return emit_user_prompt_submit(ctx, hook_event_name=str(event))
