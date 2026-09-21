# OpenCode adapter

**Hard filter (default):** `tool.definition` filters `available_skills` / skill-name enums.

**Soft inject (optional):** `chat.message` when `JEV_FILTER_MODE=soft` or `both`.

Env: `JEV_FILTER_MODE=hard|soft|both` (default `hard`).

Requires `python3 -m jev_skill_selection` on PATH.
