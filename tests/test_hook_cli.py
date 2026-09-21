from __future__ import annotations

import json
from pathlib import Path

from jev_skill_selection.cli import main
from jev_skill_selection.hook import HookContext, before_first_message
from jev_skill_selection.models import SelectionOptions


def test_hook_before_first_message(skills_root: Path):
    outcome = before_first_message(
        HookContext(
            user_message="create a powerpoint pitch deck",
            skill_roots=[skills_root],
            options=SelectionOptions(mode="local", threshold=0.1),
        )
    )
    assert any(s.name == "pptx-author" for s in outcome.kept_skills)
    assert outcome.prompt_blocks
    assert "pptx-author" in outcome.prompt_blocks[0]


def test_cli_catalog(skills_root: Path, capsys):
    code = main(["catalog", "--root", str(skills_root)])
    assert code == 0
    out = capsys.readouterr().out
    assert "git-ops" in out


def test_cli_select_json(skills_root: Path, capsys):
    code = main(
        [
            "select",
            "--root",
            str(skills_root),
            "--mode",
            "local",
            "--threshold",
            "0.1",
            "--message",
            "docker compose up my stack",
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "local"
    assert "docker-compose" in data["kept_names"]
