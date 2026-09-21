from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = REPO_ROOT / "adapters"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def adapters_root() -> Path:
    return ADAPTERS


@pytest.fixture
def skills_root() -> Path:
    return FIXTURES


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated HOME for harness tests (public-harness style)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows-friendly
    # Ensure local mode and no API key required.
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return home


@pytest.fixture
def live_enabled() -> bool:
    return os.environ.get("JEV_HARNESS_LIVE", "").strip() == "1"
