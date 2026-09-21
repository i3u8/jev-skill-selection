# Host integration (condensed)

Pre-message **keep/drop** of many skills for context size — not single-skill suggestion.
Default selection mode is **local** (no `TYPESAFE_API_KEY`). Set `JEV_MODE=jev` when using TypeSafe.

Shared helper: `jev_skill_selection.adapters.common` (parse stdin → `before_first_message` → host stdout).
CLI: `python -m jev_skill_selection select --root … --mode local -m "…" --json`.

| Host | Soft inject | Hard filter |
| --- | --- | --- |
| Claude Code | `UserPromptSubmit` → `additionalContext` | Optional phase-2: `skillOverrides` (not in hook) |
| Codex | Same wire as Claude | Optional: `[[skills.config]] enabled=false` |
| Hermes | `pre_llm_call` → `{"context":…}` | Optional later: `llm_request` middleware |
| OpenCode | `chat.message` context | `tool.definition` filters `available_skills` |

---

## Claude Code

1. `pip install -e /path/to/jev-skill-selection`
2. Merge `adapters/claude_code/settings.example.json` into `~/.claude/settings.json` or `.claude/settings.json`.
3. Point `args` at `adapters/claude_code/hook.py`.

Skills: `.claude/skills`, `~/.claude/skills`.

---

## Codex

1. Install package as above.
2. Merge `adapters/codex/hooks.example.json` into Codex `hooks.json` (path per your Codex version).
3. Point at `adapters/codex/hook.py`.

Skills: `.agents/skills`, `~/.agents/skills`, `~/.codex/skills`.

---

## Hermes

1. Install package.
2. `ln -s /path/to/jev-skill-selection/adapters/hermes ~/.hermes/plugins/jev-skill-selection`
3. Reload Hermes.

Skills: `$HERMES_HOME/skills` (default `~/.hermes/skills`).

---

## OpenCode

1. Install package (`python3 -m jev_skill_selection` must work).
2. Register `adapters/opencode` as an OpenCode plugin (see that host’s plugin docs / `@opencode-ai/plugin`).
3. Soft via `chat.message`; hard via `tool.definition` when the skill tool exposes `available_skills`.

Skills: `.opencode/skills`, `~/.config/opencode/skills`, plus Claude/Agents compat paths.

---

## Env knobs

| Variable | Meaning |
| --- | --- |
| `JEV_MODE` | `local` (default) or `jev` |
| `JEV_THRESHOLD` | Keep score cutoff (default `0.45`) |
| `JEV_MAX_KEEP` | Optional cap |
| `JEV_SKILL_ROOTS` | Override roots (`:` / `;` separated) |
| `JEV_CONTEXT_BUDGET` | Soft context char budget (default ~9000) |
| `TYPESAFE_API_KEY` | Only for `JEV_MODE=jev` |

## Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
# Live host CLIs (reserved): JEV_HARNESS_LIVE=1 python -m pytest -q tests/harness
```
