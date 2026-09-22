# Hermes adapter

**Hard filter (default):** `llm_request` middleware strips dropped skills from
`<available_skills>` blocks before the provider call.

**Soft inject (optional):** `pre_llm_call` → `{"context": "..."}` when
`JEV_FILTER_MODE=soft` or `both`.

## Install

```bash
pip install -e /path/to/jev-skill-selection
mkdir -p ~/.hermes/plugins
ln -s /path/to/jev-skill-selection/adapters/hermes ~/.hermes/plugins/jev-skill-selection
```
