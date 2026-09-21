# Codex adapter

**Hard filter (default):** write managed `[[skills.config]]` entries into
`~/.codex/config.toml` (or `$CODEX_HOME/config.toml`) with `name` + `enabled = false`
for each dropped skill.

**Soft inject (optional):** `JEV_FILTER_MODE=soft` or `both`.

**Limitation:** Codex may require a **restart** for `config.toml` changes to fully apply.
Use `JEV_FILTER_MODE=both` for same-session soft advice.

## Skill roots

- `.agents/skills`, `~/.agents/skills`, `~/.codex/skills`

## Install

1. `pip install -e /path/to/jev-skill-selection`
2. Merge `hooks.example.json` into Codex hooks config
3. Point at `adapters/codex/hook.py`
