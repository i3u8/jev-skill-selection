# OpenCode adapter

TypeScript plugin that shells out to the Python `jev_skill_selection` CLI.

## Types (`@opencode-ai/plugin`)

This adapter documents the expected shape without requiring the package at install
time (optional peer). Conceptually:

```ts
// from "@opencode-ai/plugin" (illustrative)
export type Plugin = {
  name: string;
  hooks?: {
    "chat.message"?: (input: unknown, output: unknown) => unknown;
    "tool.definition"?: (input: unknown, output: unknown) => unknown;
  };
};
```

Copy/symlink `adapters/opencode/index.ts` into `.opencode/plugins/` or `~/.config/opencode/plugins/`.
Default export is a real OpenCode `Plugin` (`async (input) => Hooks`) with `chat.message`,
`experimental.chat.system.transform`, and `tool.definition` hooks.

## Skill roots

- `.opencode/skills`
- `~/.config/opencode/skills` (`$XDG_CONFIG_HOME/opencode/skills`)
- Claude / Agents compat paths (`.claude/skills`, `.agents/skills`, …)

## Soft vs hard

| Hook | Effect |
| --- | --- |
| `chat.message` | Soft inject keep/drop context |
| `tool.definition` | Hard filter: rewrite `available_skills` to kept names only (when the skill tool exposes that field) |

## Install

```bash
pip install -e /path/to/jev-skill-selection   # Python CLI on PATH
# Register adapters/opencode with OpenCode (symlink / config — see OpenCode docs)
export JEV_MODE=local
```

Requires `python3` and the package importable as `python3 -m jev_skill_selection`.
