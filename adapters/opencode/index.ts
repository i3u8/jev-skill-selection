/**
 * OpenCode plugin — soft inject via chat.message; optional hard filter via tool.definition.
 *
 * Types: documented against `@opencode-ai/plugin` style (Plugin / Hooks).
 * We avoid a hard dependency so the repo stays Python-first; structural tests
 * parse this file without requiring node_modules.
 *
 * Soft: shell out to `python -m jev_skill_selection select --json` and append
 * keep/drop context to the user message / system hints.
 * Hard (preferred when available): filter `available_skills` on the skill tool
 * definition so dropped skills never appear.
 */

import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

/** Minimal structural stand-in for `@opencode-ai/plugin` Plugin type. */
export type OpenCodePlugin = {
  name: string;
  hooks?: Record<string, (...args: any[]) => any>;
};

export type SelectResult = {
  kept_names: string[];
  dropped_names: string[];
  kept: Array<{ name: string; score: number; reason: string }>;
  dropped: Array<{ name: string; score: number; reason: string }>;
  chars_saved?: number;
  mode?: string;
};

function env(name: string, fallback = ""): string {
  return (process.env[name] ?? fallback).trim();
}

function defaultRoots(): string[] {
  const home = homedir();
  const xdg = env("XDG_CONFIG_HOME", join(home, ".config"));
  const explicit = env("JEV_SKILL_ROOTS");
  if (explicit) {
    return explicit.split(process.platform === "win32" ? ";" : ":").filter(Boolean);
  }
  return [
    join(process.cwd(), ".opencode", "skills"),
    join(xdg, "opencode", "skills"),
    join(process.cwd(), ".claude", "skills"),
    join(home, ".claude", "skills"),
    join(process.cwd(), ".agents", "skills"),
    join(home, ".agents", "skills"),
  ];
}

/** Call the Python CLI (select --json). Returns null on failure. */
export function runSelectCli(message: string, roots: string[] = defaultRoots()): SelectResult | null {
  const mode = env("JEV_MODE", "local") || "local";
  const threshold = env("JEV_THRESHOLD", "0.45");
  const python = env("JEV_PYTHON", "python3") || "python3";
  const args = ["-m", "jev_skill_selection", "select", "--mode", mode, "--threshold", threshold, "--message", message, "--json"];
  for (const root of roots) {
    args.push("--root", root);
  }
  const res = spawnSync(python, args, {
    encoding: "utf-8",
    env: process.env,
    timeout: Number(env("JEV_SELECT_TIMEOUT_MS", "25000")) || 25000,
  });
  if (res.status !== 0 || !res.stdout?.trim()) {
    return null;
  }
  try {
    return JSON.parse(res.stdout) as SelectResult;
  } catch {
    return null;
  }
}

export function formatSoftContext(result: SelectResult): string {
  const lines = [
    "jev-skill-selection: pre-message keep/drop filter (soft inject).",
    `mode=${result.mode ?? "?"} kept=${result.kept_names?.length ?? 0} dropped=${result.dropped_names?.length ?? 0}`,
    "",
    "KEPT:",
    ...(result.kept_names ?? []).map((n) => `  - ${n}`),
    "",
    "DROPPED:",
    ...(result.dropped_names ?? []).map((n) => `  - ${n}`),
  ];
  return lines.join("\n");
}

/**
 * Factory compatible with OpenCode plugin loaders.
 *
 * Expected host hooks (names may vary by OpenCode version):
 * - `chat.message` — soft inject context into the outgoing turn
 * - `tool.definition` — hard-filter skill tool `available_skills` when present
 */
export function createJevSkillSelectionPlugin(): OpenCodePlugin {
  let lastKept: Set<string> = new Set();
  let lastDropped: Set<string> = new Set();

  return {
    name: "jev-skill-selection",
    hooks: {
      "chat.message": async (input: any, output: any) => {
        const message =
          (typeof input?.message === "string" && input.message) ||
          (typeof input?.content === "string" && input.content) ||
          (typeof output?.message === "string" && output.message) ||
          "";
        if (!message.trim()) return;
        const result = runSelectCli(message);
        if (!result) return;
        lastKept = new Set(result.kept_names ?? []);
        lastDropped = new Set(result.dropped_names ?? []);
        const ctx = formatSoftContext(result);
        if (output && typeof output === "object") {
          output.additionalContext = ctx;
          if (typeof output.message === "string") {
            output.message = `${output.message}\n\n${ctx}`;
          }
        }
        return { additionalContext: ctx, kept: [...lastKept], dropped: [...lastDropped] };
      },
      "tool.definition": async (input: any, output: any) => {
        // Hard filter: when the tool exposes available_skills, drop non-kept names.
        const toolName = String(input?.toolName ?? input?.name ?? output?.name ?? "");
        const looksLikeSkillTool = /skill/i.test(toolName);
        if (!looksLikeSkillTool || lastKept.size === 0) return;
        const target = output ?? input;
        if (!target || typeof target !== "object") return;
        const skills = target.available_skills ?? target.availableSkills;
        if (!Array.isArray(skills)) return;
        const filtered = skills.filter((s: any) => {
          const name = typeof s === "string" ? s : s?.name;
          return typeof name === "string" && lastKept.has(name);
        });
        if (target.available_skills) target.available_skills = filtered;
        if (target.availableSkills) target.availableSkills = filtered;
        return target;
      },
    },
  };
}

/** Default export for `import plugin from "..."` loaders. */
export default createJevSkillSelectionPlugin;
