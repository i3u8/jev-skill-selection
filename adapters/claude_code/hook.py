#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — hard-filter skills by default.

Default (``JEV_FILTER_MODE=hard``): write Claude ``skillOverrides`` with dropped
skills set to ``"off"``. Soft ``additionalContext`` only when mode is ``soft`` or ``both``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from jev_skill_selection.adapters.common import handle_user_prompt_submit_stdin  # noqa: E402


def main() -> int:
    stdin_text = sys.stdin.read()
    if not stdin_text.strip():
        return 0
    try:
        out = handle_user_prompt_submit_stdin(stdin_text, host="claude_code")
    except Exception as exc:  # noqa: BLE001
        print(f"jev-skill-selection claude hook error: {exc}", file=sys.stderr)
        return 0
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
