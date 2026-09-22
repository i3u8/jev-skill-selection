from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture
def skills_root() -> Path:
    return FIXTURES
