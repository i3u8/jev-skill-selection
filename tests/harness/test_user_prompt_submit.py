from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jev_skill_selection.adapters.common import (
    build_soft_context,
    emit_user_prompt_submit,
    handle_user_prompt_submit_stdin,
    parse_user_prompt_submit,
    run_selection,
)
from jev_skill_selection.models import SelectionOptions


def test_parse_user_prompt_submit_prompt_field():
    parsed = parse_user_prompt_submit(
        {"prompt": "rebase my branch and open a PR", "hook_event_name": "UserPromptSubmit"}
    )
    assert parsed["prompt"].startswith("rebase")
    assert parsed["hook_event_name"] == "UserPromptSubmit"


def test_emit_shape():
    out = emit_user_prompt_submit("hello context")
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert out["hookSpecificOutput"]["additionalContext"] == "hello context"


def test_selection_keeps_git_ops(skills_root: Path, isolated_home: Path):
    outcome = run_selection(
        "rebase my branch and open a PR",
        host="claude_code",
        skill_roots=[skills_root],
        options=SelectionOptions(mode="local", threshold=0.1),
    )
    assert "git-ops" in outcome.result.kept_names
    ctx = build_soft_context(outcome)
    assert "git-ops" in ctx
    assert "KEPT" in ctx


def test_handle_stdin_additional_context_contains_kept(skills_root: Path, isolated_home: Path, monkeypatch):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    payload = {
        "prompt": "create a powerpoint pitch deck",
        "cwd": str(skills_root.parent),
        "hook_event_name": "UserPromptSubmit",
    }
    out = handle_user_prompt_submit_stdin(json.dumps(payload), host="claude_code")
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "pptx-author" in ctx
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


@pytest.mark.parametrize("host_script", ["claude_code/hook.py", "codex/hook.py"])
def test_hook_script_subprocess(
    host_script: str,
    adapters_root: Path,
    skills_root: Path,
    repo_root: Path,
    isolated_home: Path,
    monkeypatch,
):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.setenv("PYTHONPATH", str(repo_root / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    script = adapters_root / host_script
    payload = json.dumps(
        {
            "prompt": "docker compose up my stack",
            "hook_event_name": "UserPromptSubmit",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "docker-compose" in ctx
