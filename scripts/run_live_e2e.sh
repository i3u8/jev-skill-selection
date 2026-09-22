#!/usr/bin/env bash
# Start mock LLM (if not already running via pytest fixture) and run live e2e.
# Usage:
#   ./scripts/run_live_e2e.sh
#   TYPESAFE_API_KEY=... ./scripts/run_live_e2e.sh   # exercise Jev path
#
# Requires host CLIs on PATH (claude, codex, hermes, opencode — install best-effort).
# Never prints API key values.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export JEV_HARNESS_LIVE=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -n "${TYPESAFE_API_KEY:-}" ]]; then
  export JEV_MODE=jev
  echo "TYPESAFE_API_KEY is set — live tests will use JEV_MODE=jev (key not printed)"
else
  export JEV_MODE=local
  echo "TYPESAFE_API_KEY unset — live tests use JEV_MODE=local (still live for host wiring)"
fi

# Prefer project venv if present
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
"$PY" -m pip install -e ".[dev]" -q

echo "Host CLIs:"
for c in claude codex hermes opencode; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "  OK  $c -> $(command -v "$c")"
  else
    echo "  MISS $c (corresponding live test will skip)"
  fi
done

# Pytest session fixture starts the mock LLM; no separate process required.
exec "$PY" -m pytest -m live -q tests/harness/live "$@"
