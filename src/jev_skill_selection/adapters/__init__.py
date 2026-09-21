"""Host-facing adapter helpers (Claude Code, Codex, Hermes, OpenCode)."""

from .common import (
    build_soft_context,
    default_skill_roots,
    emit_user_prompt_submit,
    options_from_env,
    parse_user_prompt_submit,
    run_selection,
)

__all__ = [
    "build_soft_context",
    "default_skill_roots",
    "emit_user_prompt_submit",
    "options_from_env",
    "parse_user_prompt_submit",
    "run_selection",
]
