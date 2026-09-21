"""Shared helpers for host hook/plugin adapters.

Hard-filter is the **default** when a host supports removing dropped skills
from the model-facing skill index / tool list (token savings). Soft inject
(additionalContext / advice text) is optional via ``JEV_FILTER_MODE``.

Modes (``JEV_FILTER_MODE``):
  - ``hard`` (default): host-native disable/override only where supported
  - ``soft``: advice/context inject only (skills bodies may still be listed)
  - ``both``: hard path + soft inject
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from ..hook import HookContext, HookOutcome, before_first_message
from ..models import SelectionOptions

# Soft-inject budget: Claude Code caps additionalContext ~10k chars.
_DEFAULT_CONTEXT_BUDGET = 9000

FilterMode = Literal["hard", "soft", "both"]

_CODEX_MANAGED_BEGIN = "# BEGIN jev-skill-selection managed"
_CODEX_MANAGED_END = "# END jev-skill-selection managed"

_AVAILABLE_SKILLS_RE = re.compile(
    r"<available_skills>.*?</available_skills>",
    re.DOTALL | re.IGNORECASE,
)


def filter_mode_from_env(default: FilterMode = "hard") -> FilterMode:
    """Return ``hard`` | ``soft`` | ``both`` from ``JEV_FILTER_MODE`` (default hard)."""
    raw = os.environ.get("JEV_FILTER_MODE", default).strip().lower() or default
    if raw in ("hard", "soft", "both"):
        return raw  # type: ignore[return-value]
    return default


def wants_hard(mode: FilterMode | None = None) -> bool:
    m = mode if mode is not None else filter_mode_from_env()
    return m in ("hard", "both")


def wants_soft(mode: FilterMode | None = None) -> bool:
    m = mode if mode is not None else filter_mode_from_env()
    return m in ("soft", "both")


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
    """Normalize Claude/Codex ``UserPromptSubmit`` stdin JSON."""
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


def build_claude_skill_overrides(
    kept_names: Sequence[str],
    dropped_names: Sequence[str],
) -> dict[str, str]:
    """Map skill names → Claude Code ``skillOverrides`` values.

    Verified against Claude Code docs/settings: values are
    ``on`` | ``name-only`` | ``user-invocable-only`` | ``off``.
    """
    overrides: dict[str, str] = {}
    for name in dropped_names:
        if name:
            overrides[str(name)] = "off"
    for name in kept_names:
        if name:
            overrides[str(name)] = "on"
    return overrides


def resolve_claude_settings_path(*, cwd: Path | None = None, home: Path | None = None) -> Path:
    """Prefer project ``.claude/settings.local.json``, else user settings."""
    home = home or Path.home()
    if cwd is not None:
        return Path(cwd) / ".claude" / "settings.local.json"
    return home / ".claude" / "settings.json"


def apply_claude_skill_overrides(
    settings_path: Path,
    overrides: Mapping[str, str],
) -> dict[str, str]:
    """Merge ``skillOverrides`` into a Claude settings JSON file."""
    settings_path = Path(settings_path)
    data: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (json.JSONDecodeError, OSError):
            data = {}

    existing = data.get("skillOverrides")
    merged: dict[str, str] = {}
    if isinstance(existing, dict):
        for k, v in existing.items():
            if isinstance(k, str) and isinstance(v, str):
                merged[k] = v
    merged.update({str(k): str(v) for k, v in overrides.items()})
    data["skillOverrides"] = merged

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(settings_path)
    return merged


def build_codex_skills_config_entries(dropped_names: Sequence[str]) -> list[dict[str, Any]]:
    """Codex ``[[skills.config]]`` rows: ``name`` + ``enabled=false`` for drops."""
    return [{"name": str(n), "enabled": False} for n in dropped_names if n]


def render_codex_skills_config_toml(dropped_names: Sequence[str]) -> str:
    """TOML fragment for managed Codex skill disables."""
    lines = [_CODEX_MANAGED_BEGIN, "# Dropped skills — hard filter (jev-skill-selection)"]
    for name in dropped_names:
        if not name:
            continue
        safe = str(name).replace("\\", "\\\\").replace('"', '\\"')
        lines.append("[[skills.config]]")
        lines.append(f'name = "{safe}"')
        lines.append("enabled = false")
        lines.append("")
    lines.append(_CODEX_MANAGED_END)
    return "\n".join(lines).rstrip() + "\n"


def apply_codex_skills_config(
    config_path: Path,
    dropped_names: Sequence[str],
) -> list[str]:
    """Rewrite the managed ``[[skills.config]]`` block in Codex ``config.toml``."""
    config_path = Path(config_path)
    text = ""
    if config_path.is_file():
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError:
            text = ""

    begin = text.find(_CODEX_MANAGED_BEGIN)
    end = text.find(_CODEX_MANAGED_END)
    if begin != -1 and end != -1 and end > begin:
        end_line = end + len(_CODEX_MANAGED_END)
        if end_line < len(text) and text[end_line] == "\n":
            end_line += 1
        text = text[:begin] + text[end_line:]

    text = text.rstrip() + ("\n\n" if text.strip() else "")
    names = [str(n) for n in dropped_names if n]
    text += render_codex_skills_config_toml(names)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(config_path)
    return names


def resolve_codex_config_path(*, home: Path | None = None) -> Path:
    home = home or Path.home()
    override = os.environ.get("CODEX_HOME", "").strip()
    if override:
        return Path(override).expanduser() / "config.toml"
    return home / ".codex" / "config.toml"


def filter_available_skills_xml(text: str, kept_names: set[str]) -> str:
    """Remove dropped skill lines from Hermes ``<available_skills>`` blocks."""

    def _repl(match: re.Match[str]) -> str:
        block = match.group(0)
        out_lines: list[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                rest = stripped[2:]
                name = rest.split(":", 1)[0].strip()
                if name and name not in kept_names:
                    continue
            out_lines.append(line)
        return "\n".join(out_lines)

    return _AVAILABLE_SKILLS_RE.sub(_repl, text)


def _filter_string_content(value: Any, kept_names: set[str]) -> Any:
    if isinstance(value, str):
        if "<available_skills>" in value.lower():
            return filter_available_skills_xml(value, kept_names)
        return value
    if isinstance(value, list):
        return [_filter_string_content(v, kept_names) for v in value]
    if isinstance(value, dict):
        return {k: _filter_string_content(v, kept_names) for k, v in value.items()}
    return value


def filter_hermes_llm_request(
    request: Mapping[str, Any],
    kept_names: Sequence[str],
) -> dict[str, Any]:
    """Hard-filter Hermes provider kwargs: strip dropped skills from messages."""
    kept = {str(n) for n in kept_names if n}
    out = dict(request)
    for key in ("messages", "input"):
        if key in out:
            out[key] = _filter_string_content(out[key], kept)
    for key in ("extra_body", "body"):
        if isinstance(out.get(key), dict):
            nested = dict(out[key])
            for nk in ("messages", "input"):
                if nk in nested:
                    nested[nk] = _filter_string_content(nested[nk], kept)
            out[key] = nested
    return out


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


def e2e_log_selection(
    *,
    host: str,
    message: str,
    outcome: HookOutcome,
    soft_context: str | None = None,
    filter_mode: str | None = None,
    hard_applied: bool | None = None,
) -> None:
    """Append a JSON line to ``JEV_E2E_LOG`` when set (live harness side-channel)."""
    log_path = os.environ.get("JEV_E2E_LOG", "").strip()
    if not log_path:
        return
    import time

    payload = {
        "ts": time.time(),
        "host": host,
        "message": message[:500],
        "mode": outcome.result.mode,
        "filter_mode": filter_mode or filter_mode_from_env(),
        "hard_applied": hard_applied,
        "kept_names": list(outcome.result.kept_names),
        "dropped_names": list(outcome.result.dropped_names),
        "chars_saved": outcome.result.chars_saved,
        "soft_context_excerpt": (soft_context or "")[:1500],
        "marker": "jev_skill_selection_hook_executed",
    }
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handle_user_prompt_submit_stdin(
    stdin_text: str,
    *,
    host: str,
    skill_roots: Sequence[str | Path] | None = None,
    options: SelectionOptions | None = None,
    filter_mode: FilterMode | None = None,
) -> dict[str, Any]:
    """End-to-end: stdin JSON → selection → hard filter (default) + optional soft stdout."""
    mode = filter_mode if filter_mode is not None else filter_mode_from_env()
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
    hard_applied = False
    soft_ctx = ""

    host_key = host.lower().replace("-", "_")
    if wants_hard(mode):
        if host_key in ("claude", "claude_code"):
            overrides = build_claude_skill_overrides(
                outcome.result.kept_names, outcome.result.dropped_names
            )
            path = resolve_claude_settings_path(cwd=cwd)
            apply_claude_skill_overrides(path, overrides)
            hard_applied = True
        elif host_key == "codex":
            apply_codex_skills_config(
                resolve_codex_config_path(),
                outcome.result.dropped_names,
            )
            hard_applied = True

    if wants_soft(mode):
        soft_ctx = build_soft_context(outcome)
        e2e_log_selection(
            host=host,
            message=parsed["prompt"],
            outcome=outcome,
            soft_context=soft_ctx,
            filter_mode=mode,
            hard_applied=hard_applied,
        )
        return emit_user_prompt_submit(soft_ctx, hook_event_name=str(event))

    e2e_log_selection(
        host=host,
        message=parsed["prompt"],
        outcome=outcome,
        soft_context=None,
        filter_mode=mode,
        hard_applied=hard_applied,
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": str(event),
        }
    }
