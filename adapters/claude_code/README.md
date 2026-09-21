# Claude Code adapter

**Soft inject** via `UserPromptSubmit`: keep/drop guidance (+ kept skill bodies within budget) → `hookSpecificOutput.additionalContext`.

**Hard filter (optional, phase 2):** Claude `skillOverrides` / disabling skills in settings — not wired by this hook. Soft inject does **not** remove skills from Claude’s index; it steers the model toward kept skills.

## Skill roots

- `.claude/skills` (project)
- `~/.claude/skills` (user)

Override with `JEV_SKILL_ROOTS` (`:` / `;` separated).

## Install

```bash
# From this repo (or after pip install -e .)
python -m pip install -e /path/to/jev-skill-selection

# Merge adapters/claude_code/settings.example.json into:
#   ~/.claude/settings.json   or   .claude/settings.json
# Point `args` at the absolute path of hook.py if not using CLAUDE_PROJECT_DIR.
```

Example snippet:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["/abs/path/to/jev-skill-selection/adapters/claude_code/hook.py"],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Default mode is **local** (no `TYPESAFE_API_KEY`). Set `JEV_MODE=jev` for TypeSafe Jev.

## Wire format

- **stdin:** `{ "prompt": "...", "cwd": "...", "hook_event_name": "UserPromptSubmit", ... }`
- **stdout:** `{ "hookSpecificOutput": { "hookEventName": "UserPromptSubmit", "additionalContext": "..." } }`
