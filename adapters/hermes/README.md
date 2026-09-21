# Hermes adapter

**Best native fit:** plugin under `~/.hermes/plugins/<name>/` with `plugin.yaml` + `register(ctx)`.

Registers `pre_llm_call` and returns `{"context": "<soft keep/drop text>"}` wrapping `before_first_message`.

## Skill roots

- `$HERMES_HOME/skills` (default `~/.hermes/skills`)
- `.hermes/skills` (project)

## Install

```bash
pip install -e /path/to/jev-skill-selection
mkdir -p ~/.hermes/plugins
ln -s /path/to/jev-skill-selection/adapters/hermes ~/.hermes/plugins/jev-skill-selection
# Restart Hermes / reload plugins
```

## Soft vs hard

| Mode | What you get |
| --- | --- |
| Soft (this plugin) | `context` string injected before the LLM call |
| Hard (optional later) | `llm_request` middleware to rewrite the skill index — not implemented |

Default `JEV_MODE=local`.
