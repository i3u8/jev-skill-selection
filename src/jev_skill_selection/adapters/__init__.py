"""Host-facing adapter helpers (Claude Code, Codex, Hermes, OpenCode)."""

from .common import (
    apply_claude_skill_overrides,
    apply_codex_skills_config,
    build_claude_skill_overrides,
    build_codex_skills_config_entries,
    build_soft_context,
    default_skill_roots,
    emit_user_prompt_submit,
    filter_hermes_llm_request,
    filter_mode_from_env,
    options_from_env,
    parse_user_prompt_submit,
    render_codex_skills_config_toml,
    run_selection,
    wants_hard,
    wants_soft,
)

__all__ = [
    "apply_claude_skill_overrides",
    "apply_codex_skills_config",
    "build_claude_skill_overrides",
    "build_codex_skills_config_entries",
    "build_soft_context",
    "default_skill_roots",
    "emit_user_prompt_submit",
    "filter_hermes_llm_request",
    "filter_mode_from_env",
    "options_from_env",
    "parse_user_prompt_submit",
    "render_codex_skills_config_toml",
    "run_selection",
    "wants_hard",
    "wants_soft",
]
