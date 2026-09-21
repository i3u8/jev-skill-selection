#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — soft-inject keep/drop context.

Reads stdin JSON (field ``prompt``), runs local/jev selection against Claude
skill roots, prints JSON with ``hookSpecificOutput.additionalContext``.

Env:
  JEV_MODE=local|jev (default local)
  JEV_THRESHOLD, JEV_MAX_KEEP, JEV_SKILL_ROOTS (os.pathsep), JEV_CONTEXT_BUDGET
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from a git checkout without install.
_REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from jev_skill_selection.adapters.common import handle_user_prompt_submit_stdin  # noqa: E402


def main() -> int:
    stdin_text = sys.stdin.read()
    if not stdin_text.strip():
        # Empty stdin: no-op (do not block the prompt).
        return 0
    try:
        out = handle_user_prompt_submit_stdin(stdin_text, host="claude_code")
    except Exception as exc:  # noqa: BLE001 — never block the user prompt
        print(f"jev-skill-selection claude hook error: {exc}", file=sys.stderr)
        return 0
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
