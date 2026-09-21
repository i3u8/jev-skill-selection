from __future__ import annotations

import os
import shutil

import pytest


@pytest.mark.skipif(
    os.environ.get("JEV_HARNESS_LIVE", "").strip() != "1",
    reason="JEV_HARNESS_LIVE!=1 — live host CLI runs reserved for future",
)
def test_live_reserved_stub():
    """Placeholder: when JEV_HARNESS_LIVE=1 and host CLIs exist, exercise them here."""
    has_any = any(shutil.which(c) for c in ("claude", "codex", "hermes", "opencode"))
    if not has_any:
        pytest.skip("JEV_HARNESS_LIVE=1 but no host CLIs (claude/codex/hermes/opencode) on PATH")
    pytest.skip("Live harness not implemented yet — reserved stub")
