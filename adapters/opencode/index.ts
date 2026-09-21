/**
 * OpenCode plugin — soft inject via chat.message (+ experimental.chat.system.transform);
 * optional hard filter via tool.definition.
 *
 * Export shape matches `@opencode-ai/plugin`:
 *   `Plugin = (input) => Promise<Hooks>`
 *
 * Soft: shell out to `python -m jev_skill_selection select --json` and inject
 * keep/drop context into user message parts / system prompt.
 * Hard: rewrite skill-tool description/parameters so dropped skills never appear
 * when `available_skills` (or enum of skill names) is observable.
 */

import { appendFileSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

/** Minimal structural stand-in for `@opencode-ai/plugin` Plugin type. */
export type OpenCodePlugin = (input: any, options?: any) => Promise<Record<string, any>>;

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
  const args = [
    "-m",
    "jev_skill_selection",
    "select",
    "--mode",
    mode,
    "--threshold",
    threshold,
    "--message",
    message,
    "--json",
  ];
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

function e2eLog(message: string, result: SelectResult, soft: string): void {
  const logPath = env("JEV_E2E_LOG");
  if (!logPath) return;
  try {
    mkdirSync(dirname(logPath), { recursive: true });
    const payload = {
      ts: Date.now() / 1000,
      host: "opencode",
      message: message.slice(0, 500),
      mode: result.mode ?? "?",
      kept_names: result.kept_names ?? [],
      dropped_names: result.dropped_names ?? [],
      chars_saved: result.chars_saved ?? 0,
      soft_context_excerpt: soft.slice(0, 1500),
      marker: "jev_skill_selection_hook_executed",
    };
    appendFileSync(logPath, JSON.stringify(payload) + "\n", "utf-8");
  } catch {
    // never block the host
  }
}

function extractUserText(output: any, input?: any): string {
  if (output && typeof output === "object") {
    const msg = output.message;
    if (typeof msg === "string") return msg;
    if (msg && typeof msg.content === "string") return msg.content;
    if (Array.isArray(output.parts)) {
      return output.parts
        .map((p: any) => {
          if (typeof p === "string") return p;
          if (p?.type === "text") return String(p.text ?? p.content ?? "");
          if (typeof p?.text === "string") return p.text;
          return "";
        })
        .filter(Boolean)
        .join("\n");
    }
  }
  if (typeof input?.message === "string") return input.message;
  if (typeof input?.content === "string") return input.content;
  return "";
}

function filterAvailableSkills(params: any, kept: Set<string>): any {
  if (!params || typeof params !== "object") return params;
  const next: any = Array.isArray(params) ? [...params] : { ...params };
  for (const key of ["available_skills", "availableSkills", "skills"]) {
    const val = next[key];
    if (Array.isArray(val)) {
      next[key] = val.filter((s: any) => {
        const name = typeof s === "string" ? s : s?.name;
        return typeof name === "string" && kept.has(name);
      });
    }
  }
  if (next.properties && typeof next.properties === "object") {
    next.properties = { ...next.properties };
    for (const key of Object.keys(next.properties)) {
      const prop = next.properties[key];
      if (prop?.enum && Array.isArray(prop.enum)) {
        const filtered = prop.enum.filter((n: any) => typeof n === "string" && kept.has(n));
        // Only rewrite when it looks like a skill-name enum (intersected with kept/dropped).
        if (filtered.length && filtered.length < prop.enum.length) {
          next.properties[key] = { ...prop, enum: filtered };
        }
      }
    }
  }
  return next;
}

function buildHooks() {
  let lastKept: Set<string> = new Set();
  let lastDropped: Set<string> = new Set();
  let lastSoft = "";

  return {
    "chat.message": async (input: any, output: any) => {
      const message = extractUserText(output, input);
      if (!message.trim()) return;
      const result = runSelectCli(message);
      if (!result) return;
      lastKept = new Set(result.kept_names ?? []);
      lastDropped = new Set(result.dropped_names ?? []);
      const ctx = formatSoftContext(result);
      lastSoft = ctx;
      e2eLog(message, result, ctx);
      if (output && typeof output === "object") {
        (output as any).additionalContext = ctx;
        if (Array.isArray(output.parts)) {
          output.parts = [...output.parts, { type: "text", text: `\n\n${ctx}` }];
        }
      }
    },
    "experimental.chat.system.transform": async (_input: any, output: any) => {
      if (!lastSoft || !output || !Array.isArray(output.system)) return;
      output.system.push(lastSoft);
    },
    "tool.definition": async (input: any, output: any) => {
      const toolName = String(input?.toolID ?? input?.toolName ?? input?.name ?? "");
      const looksLikeSkillTool = /skill/i.test(toolName);
      if (!looksLikeSkillTool || lastKept.size === 0 || !output) return;
      if (typeof output.description === "string" && lastDropped.size) {
        let desc = output.description;
        for (const name of lastDropped) {
          const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          desc = desc.replace(new RegExp(`\\b${escaped}\\b`, "gi"), "");
        }
        output.description = desc;
      }
      if (output.parameters) {
        output.parameters = filterAvailableSkills(output.parameters, lastKept);
      }
      for (const key of ["available_skills", "availableSkills"] as const) {
        const skills = (output as any)[key];
        if (Array.isArray(skills)) {
          (output as any)[key] = skills.filter((s: any) => {
            const name = typeof s === "string" ? s : s?.name;
            return typeof name === "string" && lastKept.has(name);
          });
        }
      }
    },
  };
}

/**
 * Legacy/test factory returning `{ name, hooks }` (used by offline harness).
 * Real OpenCode loads the default Plugin export below.
 */
export function createJevSkillSelectionPlugin(): {
  name: string;
  hooks: Record<string, (...args: any[]) => any>;
} {
  return {
    name: "jev-skill-selection",
    hooks: buildHooks(),
  };
}

/** Real OpenCode Plugin entrypoint. */
const JevSkillSelectionPlugin: OpenCodePlugin = async (_input, _options) => buildHooks();

export default JevSkillSelectionPlugin;
