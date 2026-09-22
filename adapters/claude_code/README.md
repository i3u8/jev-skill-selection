# Claude Code adapter

**Hard filter (default):** on `UserPromptSubmit`, write Claude Code `skillOverrides`
into `.claude/settings.local.json` with dropped skills set to `"off"` (token savings).
Values: `on` | `name-only` | `user-invocable-only` | `off` (Claude Code docs).

**Soft inject (optional):** `JEV_FILTER_MODE=soft` or `both` → `additionalContext`.

| Mode (`JEV_FILTER_MODE`) | Behavior |
| --- | --- |
| `hard` (default) | `skillOverrides` only |
| `soft` | `additionalContext` only |
| `both` | overrides + context |

## Skill roots

- `.claude/skills` (project)
- `~/.claude/skills` (user)

## Install

```bash
python -m pip install -e /path/to/jev-skill-selection
# Merge adapters/claude_code/settings.example.json into ~/.claude/settings.json or .claude/settings.json
```

## Wire format

- **stdin:** `{ "prompt": "...", "cwd": "...", "hook_event_name": "UserPromptSubmit", ... }`
- **stdout (hard):** `{ "hookSpecificOutput": { "hookEventName": "UserPromptSubmit" } }`
- **side effect (hard):** writes `skillOverrides` under cwd `.claude/settings.local.json`
