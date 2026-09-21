# Codex adapter

Uses the same **UserPromptSubmit** stdin/stdout JSON as Claude Code (soft inject → `additionalContext`).

## Skill roots

- `.agents/skills`
- `~/.agents/skills`
- `~/.codex/skills`

## Install

1. `pip install -e /path/to/jev-skill-selection`
2. Copy/merge `hooks.example.json` into your Codex hooks config (often `hooks.json` next to the agent, or the host’s documented hooks path).
3. Point `args` at `adapters/codex/hook.py`.

## Soft vs hard

| Mode | What you get |
| --- | --- |
| Soft (this hook) | Keep/drop context injected before the model turn |
| Hard (optional) | In Codex config, set `[[skills.config]]` with `enabled = false` for dropped names after a selection pass — not automated here |

```toml
# Example hard filter (manual / scripted), not done by the hook:
# [[skills.config]]
# name = "pptx-author"
# enabled = false
```

Env: `JEV_MODE`, `JEV_THRESHOLD`, `JEV_SKILL_ROOTS`, …
