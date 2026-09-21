"""Backward-compatible entry: live tests live under ``tests/harness/live/``.

When ``JEV_HARNESS_LIVE!=1``, this module documents the gate and stays skipped.
When enabled, the real suite in ``tests/harness/live/test_live_hosts.py`` runs.
"""

from __future__ import annotations

import os
import shutil

import pytest


@pytest.mark.skipif(
    os.environ.get("JEV_HARNESS_LIVE", "").strip() != "1",
    reason="JEV_HARNESS_LIVE!=1 — see tests/harness/live/ and scripts/run_live_e2e.sh",
)
def test_live_suite_pointer():
    """Smoke: at least one host CLI should exist when live mode is on."""
    has_any = any(shutil.which(c) for c in ("claude", "codex", "hermes", "opencode"))
    if not has_any:
        pytest.skip("JEV_HARNESS_LIVE=1 but no host CLIs (claude/codex/hermes/opencode) on PATH")
    # Real assertions are in tests/harness/live/test_live_hosts.py
    assert True
