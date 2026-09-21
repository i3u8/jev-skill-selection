# jev-skill-selection

**在第一条模型消息之前**，用 TypeSafe Jev（或本地关键词）对技能目录做 **keep/drop**，只把保留的 `SKILL.md` 注入提示词，从而压缩 agent 上下文。

Pre-message hook: filter which skills enter the prompt **before** the first LLM call. Keep/drop many skills for context size — **not** a single-skill suggester.

> 与 [TypeSafe skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion.md) 的区别：那边是「最多推荐 **一个** 技能名」；本库是「对 **多个** 技能做保留/丢弃」，服务的是 **上下文体积**，不是单点推荐。

## 架构 / Architecture

```
SKILL.md roots ──► catalog loader (closed set)
                         │
user message ──────────► select_skills(mode=local|jev)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         local keywords      TypeSafe Jev API
         (no API key)        Noul keep? / Choice soft scores
              │                     │
              └──────────┬──────────┘
                         ▼
              SelectionResult {kept, dropped, chars_saved}
                         │
              pre-message hook adapter
                         ▼
              only kept skills → system / prompt
```

| 模块 | 作用 |
| --- | --- |
| `catalog.py` | 扫描 `--root` 下的 `SKILL.md`（YAML frontmatter `name`/`description` + body） |
| `select.py` | 核心 API `select_skills(...)` |
| `local_mode.py` | 无网络关键词/元数据短名单 |
| `jev_client.py` | stdlib `urllib` 客户端 → `POST /v1/systemone` |
| `jev_mode.py` | 每技能一条 Noul（默认）或 Choice 概率作 soft score |
| `hook.py` | 宿主无关的 pre-message 适配示意（Claude Code / Codex / 通用中间件） |
| `cli.py` | `python -m jev_skill_selection catalog\|select` |

**Jev 请求约定**（官方：https://docs.typesafe.ai ）

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`
- Auth: `Authorization: Bearer $TYPESAFE_API_KEY`
- Env: `TYPESAFE_API_KEY`、`TYPESAFE_BASE_URL`、`TYPESAFE_DEFAULT_MODEL`
- 默认 model: `jev-1.13.0`（为可复现而钉版本；请对照 [Models](https://docs.typesafe.ai/models.md) 核实；也可用 `jev-latest`）

## 安装 / Install

```bash
python -m pip install -e ".[dev]"
# 或仅跑测试依赖
python -m pip install pytest
```

Python **3.10+**，运行时 **零第三方依赖**（仅 stdlib）。开发可选 `pytest`。

## CLI

```bash
# 列出封闭技能集
python -m jev_skill_selection catalog --root ./tests/fixtures/skills

# 本地模式（无需 API key）
python -m jev_skill_selection select \
  --root ./tests/fixtures/skills \
  --mode local \
  --message "rebase my branch and open a PR"

# Jev 模式
export TYPESAFE_API_KEY=...
python -m jev_skill_selection select \
  --root ./tests/fixtures/skills \
  --mode jev \
  --model jev-1.13.0 \
  --message "rebase my branch and open a PR" \
  --json
```

## 库用法 / Library

```python
from jev_skill_selection import load_catalog, select_skills, SelectionOptions
from jev_skill_selection.hook import before_first_message, HookContext

catalog = load_catalog(["./skills"])
result = select_skills(
    "fix the pytest traceback",
    catalog,
    SelectionOptions(mode="local", threshold=0.45, max_keep=5),
)
print(result.kept_names, result.chars_saved)

# Pre-message hook
outcome = before_first_message(HookContext(
    user_message="...",
    skill_roots=["./skills"],
    options=SelectionOptions(mode="jev"),
))
system_prompt_extra = "\n\n".join(outcome.prompt_blocks)
```

宿主接入见 `adapters/` 与 `docs/INTEGRATION.md`；核心仍见 `src/jev_skill_selection/hook.py`。

## 测试 / Tests

单元测试 **全部 mock Jev、无真实网络**：

```bash
python -m pip install pytest
python -m pytest -q
```

## 开放决策 / Open decisions

1. **默认阈值** `0.45`：需按你的目录标定；Jev Noul 与 local Jaccard 不可直接横比。
2. **默认策略** `noul`（每技能独立 keep/drop，可多留）；`choice` 更接近「软推荐」，适合小目录。
3. **local 预过滤**（Jev 前 top-k）：省 token，但可能误杀边缘相关技能。
4. **Model pin** `jev-1.13.0`：发布后请再核对官方 model 列表。
5. **宿主钩子**：各 agent 产品的扩展点仍在演进；`adapters/` 提供 thin soft-inject 适配，硬过滤按宿主可选。


## Host adapters

Thin adapters under `adapters/` soft-inject keep/drop context before the first model turn.
See **[docs/INTEGRATION.md](docs/INTEGRATION.md)** for install per host.

| Host | Path | Soft | Hard (optional) |
| --- | --- | --- | --- |
| Claude Code | `adapters/claude_code/` | `UserPromptSubmit` → `additionalContext` | `skillOverrides` (phase 2) |
| Codex | `adapters/codex/` | same wire as Claude | `[[skills.config]] enabled=false` |
| Hermes | `adapters/hermes/` | `pre_llm_call` → `context` | `llm_request` middleware later |
| OpenCode | `adapters/opencode/` | `chat.message` | `tool.definition` → filter `available_skills` |

Shared helpers: `jev_skill_selection.adapters.common` (stdin parse + host stdout). Default `JEV_MODE=local` (no API key).

## How to test

```bash
python -m pip install -e ".[dev]"
python -m pytest -q                 # unit + harness (offline)
# Optional future live host runs:
./scripts/run_live_e2e.sh
# JEV_HARNESS_LIVE=1 python -m pytest -m live -q tests/harness/live
```

Harness tests live in `tests/harness/` (static adapter files, UserPromptSubmit simulation, Hermes register smoke, OpenCode structural/TS check).

## License

MIT
