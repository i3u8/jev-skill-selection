# Host integration (condensed)

Pre-message **keep/drop** of many skills for context size — not single-skill suggestion.
Default selection mode is **local** (no `TYPESAFE_API_KEY`). Set `JEV_MODE=jev` when using TypeSafe.

**Filter mode default is hard** (`JEV_FILTER_MODE=hard`): dropped skills are removed from
host-facing skill lists / overrides / config **before** the model sees them (token savings).
Soft inject (`additionalContext` / advice text) alone leaves skill bodies/listings in context.

Shared helper: `jev_skill_selection.adapters.common` (parse stdin → `before_first_message` → hard path + optional soft stdout).
CLI: `python -m jev_skill_selection select --root … --mode local -m "…" --json`.

| Host | Soft inject | Hard filter (default) | Notes |
| --- | --- | --- | --- |
| Claude Code | `UserPromptSubmit` → `additionalContext` | Writes `skillOverrides` (`"off"` for drops) to `.claude/settings.local.json` | Verified Claude Code settings API |
| Codex | Same wire as Claude | `[[skills.config]] name=… enabled=false` in `~/.codex/config.toml` | May need Codex **restart** for config to apply |
| Hermes | `pre_llm_call` → `{"context":…}` | `llm_request` middleware strips `<available_skills>` | Soft is fallback only |
| OpenCode | `chat.message` context | `tool.definition` filters `available_skills` | Soft secondary |

---

## Claude Code

1. `pip install -e /path/to/jev-skill-selection`
2. Merge `adapters/claude_code/settings.example.json` into `~/.claude/settings.json` or `.claude/settings.json`.
3. Point `args` at `adapters/claude_code/hook.py`.

Skills: `.claude/skills`, `~/.claude/skills`.

Hard path uses documented `skillOverrides` values: `on` | `name-only` | `user-invocable-only` | `off`.

---

## Codex

1. Install package as above.
2. Merge `adapters/codex/hooks.example.json` into Codex `hooks.json` (path per your Codex version).
3. Point at `adapters/codex/hook.py`.

Skills: `.agents/skills`, `~/.agents/skills`, `~/.codex/skills`.

Hard path appends a managed block to `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`).
Codex documents that config changes may require a restart — see adapter README.

---

## Hermes

1. Install package.
2. `ln -s /path/to/jev-skill-selection/adapters/hermes ~/.hermes/plugins/jev-skill-selection`
3. Reload Hermes.

Skills: `$HERMES_HOME/skills` (default `~/.hermes/skills`).

Hard path: `provides_middleware: [llm_request]` rewrites provider kwargs. Soft `pre_llm_call` only when `JEV_FILTER_MODE=soft|both`.

---

## OpenCode

1. Install package (`python3 -m jev_skill_selection` must work).
2. Register `adapters/opencode` as an OpenCode plugin (see that host’s plugin docs / `@opencode-ai/plugin`).
3. Hard via `tool.definition` (default); soft via `chat.message` when requested.

Skills: `.opencode/skills`, `~/.config/opencode/skills`, plus Claude/Agents compat paths.

---

## Env knobs

| Variable | Meaning |
| --- | --- |
| `JEV_FILTER_MODE` | `hard` (default) \| `soft` \| `both` |
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
# Live host CLIs:
# ./scripts/run_live_e2e.sh
# JEV_HARNESS_LIVE=1 python -m pytest -m live -q tests/harness/live
```


---

## Live e2e (real host CLIs + mocked LLM)

Gate: set ``JEV_HARNESS_LIVE=1``. Default offline ``pytest`` does **not** run these.

What the suite does:

1. Installs fixture skills into an isolated ``HOME`` / project tree.
2. Registers the corresponding adapter under ``adapters/``.
3. Starts a local mock LLM (`tests/harness/live/mock_llm_server.py`) — **no Anthropic/OpenAI spend**.
4. Runs one non-interactive prompt: ``rebase my branch and open a PR``.
5. Asserts: hook marker (`JEV_E2E_LOG`), keep set includes ``git-ops``, mock request **after** hook, soft-inject text in mock body when observable.

### Run

```bash
# Best-effort host installs (once per machine):
npm install -g @anthropic-ai/claude-code @openai/codex opencode-ai
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-browser
# OpenCode alternative: curl -fsSL https://opencode.ai/install | bash

./scripts/run_live_e2e.sh
# or:
JEV_HARNESS_LIVE=1 python -m pytest -m live -q tests/harness/live
```

With TypeSafe Jev (real network to TypeSafe only; LLM still mocked):

```bash
export TYPESAFE_API_KEY=...   # never commit / never print
TYPESAFE_API_KEY="$TYPESAFE_API_KEY" ./scripts/run_live_e2e.sh
```

Without ``TYPESAFE_API_KEY``, live tests still exercise **host wiring** with ``JEV_MODE=local`` and report ``mode=local`` in the e2e log.

### Mock LLM env overrides (per host)

| Host | How to point at mock |
| --- | --- |
| Claude Code | ``ANTHROPIC_BASE_URL=http://127.0.0.1:PORT`` + ``ANTHROPIC_API_KEY=sk-mock`` (also ``settings.json`` ``env`` block). Do **not** pass ``--bare`` (skips hooks). Use ``claude -p … --dangerously-skip-permissions``. |
| Codex | ``openai_base_url`` / custom ``[model_providers.*]`` with ``wire_api = "responses"`` (chat wire API is retired). ``OPENAI_API_KEY=sk-mock``. Hooks: ``~/.codex/hooks.json`` + ``codex exec --dangerously-bypass-hook-trust``. |
| Hermes | ``model.provider: custom`` + ``model.base_url`` in ``$HERMES_HOME/config.yaml``, or ``OPENAI_BASE_URL``. Plugin symlink: ``$HERMES_HOME/plugins/jev-skill-selection`` → ``adapters/hermes``. ``hermes -z "…" --provider custom --yolo``. |
| OpenCode | Prefer ``opencode.json`` custom provider with ``options.baseURL`` (``OPENAI_BASE_URL`` alone is unreliable). Place plugin under ``.opencode/plugins/`` or ``~/.config/opencode/plugins/``. ``opencode run "…" -m mock/mock-model --auto``. |

Request log: JSONL from the mock server (roles + full body) for soft-inject / ordering assertions. Adapter side-channel: ``JEV_E2E_LOG=/path/to.jsonl``.

### Known headless blockers

Document remaining auth/interactive blockers in the PR body when a host cannot complete without a TTY. Do **not** fake a green live test for a missing CLI — skip with reason.
