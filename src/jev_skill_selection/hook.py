"""Pre-message hook seam — host-agnostic adapter.

Call :func:`before_first_message` (or :func:`select_skills` directly) *before*
the first LLM request so only kept skills are injected into the system/prompt
context.

This module does not depend on Claude Code, Codex, or any specific harness.
Wire it in middleware / a plugin that can mutate the prompt assembly step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .catalog import Skill, load_catalog
from .models import SelectionOptions, SelectionResult
from .select import filter_catalog, select_skills


@dataclass
class HookContext:
    """Inputs available at the pre-message boundary."""

    user_message: str
    skill_roots: Sequence[str | Path]
    options: SelectionOptions | None = None


@dataclass
class HookOutcome:
    result: SelectionResult
    kept_skills: list[Skill]
    # Ready-to-inject text blocks (host decides where they go).
    prompt_blocks: list[str]


def render_skill_block(skill: Skill) -> str:
    """Default serialization of a kept skill for prompt injection."""
    return (
        f'<skill name="{skill.name}">\n'
        f"{skill.description}\n\n"
        f"{skill.body}\n"
        f"</skill>"
    )


def before_first_message(
    ctx: HookContext,
    *,
    renderer: Callable[[Skill], str] | None = None,
) -> HookOutcome:
    """Load catalog -> select -> return kept skills + rendered blocks.

    Example (generic middleware)::

        outcome = before_first_message(HookContext(
            user_message=user_text,
            skill_roots=["~/.agents/skills", "./skills"],
            options=SelectionOptions(mode="local"),  # or mode="jev"
        ))
        system_prompt += "\\n".join(outcome.prompt_blocks)

    Claude Code / Codex: register an equivalent step in whatever extension
    point runs before the first model turn (plugin hook, middleware, or a
    wrapper around your prompt builder). The core stays host-agnostic.
    """
    catalog = load_catalog(ctx.skill_roots)
    result = select_skills(ctx.user_message, catalog, ctx.options)
    kept = filter_catalog(catalog, result)
    render = renderer or render_skill_block
    blocks = [render(s) for s in kept]
    return HookOutcome(result=result, kept_skills=kept, prompt_blocks=blocks)


def sketch_generic_middleware(
    user_message: str, roots: list[str], mode: str = "local"
) -> HookOutcome:
    """Generic agent middleware sketch."""
    return before_first_message(
        HookContext(
            user_message=user_message,
            skill_roots=roots,
            options=SelectionOptions(mode=mode),  # type: ignore[arg-type]
        )
    )


CLAUDE_CODE_NOTES = """
Claude Code
|-----------
Preferred: ``adapters/claude_code/hook.py`` on ``UserPromptSubmit`` (see
``docs/INTEGRATION.md``). Soft inject → ``hookSpecificOutput.additionalContext``.

Library-only equivalent::

    from jev_skill_selection.hook import before_first_message, HookContext
    from jev_skill_selection import SelectionOptions

    outcome = before_first_message(HookContext(
        user_message=latest_user_text,
        skill_roots=[".claude/skills", "~/.claude/skills"],
        options=SelectionOptions(mode="local"),  # or mode="jev"
    ))
"""

CODEX_NOTES = """
Codex / OpenAI-style agents
|---------------------------
Preferred: ``adapters/codex/hook.py`` (same UserPromptSubmit wire as Claude).

Library-only::

    outcome = before_first_message(HookContext(
        user_message=user_message,
        skill_roots=[".agents/skills", "~/.agents/skills", "~/.codex/skills"],
        options=SelectionOptions(mode="local"),
    ))
"""
