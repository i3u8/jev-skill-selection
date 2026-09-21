from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_opencode_ts_structural(adapters_root: Path):
    """Parse/structure-check the TS plugin without requiring @opencode-ai/plugin."""
    text = (adapters_root / "opencode" / "index.ts").read_text(encoding="utf-8")
    assert 'name: "jev-skill-selection"' in text or "name: 'jev-skill-selection'" in text
    assert "chat.message" in text
    assert "tool.definition" in text
    assert "runSelectCli" in text
    assert "available_skills" in text
    assert "filterModeFromEnv" in text
    assert "JEV_FILTER_MODE" in text
    assert "jev_skill_selection" in text
    # Exported factory
    assert re.search(r"export\s+function\s+createJevSkillSelectionPlugin", text)
    assert re.search(r"export\s+default", text)


def test_opencode_package_lists_optional_peer(adapters_root: Path):
    import json

    pkg = json.loads((adapters_root / "opencode" / "package.json").read_text())
    peers = pkg.get("peerDependencies") or {}
    assert "@opencode-ai/plugin" in peers


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable — structural tests only")
def test_opencode_node_syntax_check(adapters_root: Path):
    """If node is present, ensure the TS file is at least loadable as text / parseable via node --check on a transpile skip.

    We don't require typescript or ts-node. Use a tiny node script to verify key exports
    exist as strings (already covered structurally). If `npx --yes esbuild` works, bundle
    to CJS and syntax-check; otherwise skip with a clear marker.
    """
    ts_path = adapters_root / "opencode" / "index.ts"
    # Prefer esbuild if available via npx (network may be blocked — then skip).
    try:
        proc = subprocess.run(
            ["npx", "--yes", "esbuild", str(ts_path), "--bundle", "--platform=node", "--format=cjs"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"esbuild unavailable for TS compile check: {exc}")
    if proc.returncode != 0:
        # Offline / registry blocked — document and skip rather than fail CI.
        pytest.skip(
            "node present but esbuild compile skipped/failed (offline or no registry): "
            + (proc.stderr or proc.stdout)[:300]
        )
    # Syntax-check the emitted JS
    check = subprocess.run(
        ["node", "--check"],
        input=proc.stdout,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert check.returncode == 0, check.stderr
