"""Assert hard-filter payloads omit dropped skills (offline)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jev_skill_selection.adapters.common import (
    apply_claude_skill_overrides,
    apply_codex_skills_config,
    build_claude_skill_overrides,
    filter_available_skills_xml,
    filter_hermes_llm_request,
    filter_mode_from_env,
    handle_user_prompt_submit_stdin,
    render_codex_skills_config_toml,
    resolve_codex_config_path,
    run_selection,
    wants_hard,
    wants_soft,
)
from jev_skill_selection.models import SelectionOptions


def test_filter_mode_default_hard(monkeypatch):
    monkeypatch.delenv("JEV_FILTER_MODE", raising=False)
    assert filter_mode_from_env() == "hard"
    assert wants_hard() is True
    assert wants_soft() is False


@pytest.mark.parametrize(
    "value,hard,soft",
    [
        ("hard", True, False),
        ("soft", False, True),
        ("both", True, True),
    ],
)
def test_filter_mode_env(monkeypatch, value, hard, soft):
    monkeypatch.setenv("JEV_FILTER_MODE", value)
    assert wants_hard() is hard
    assert wants_soft() is soft


def test_claude_skill_overrides_drops_off():
    ov = build_claude_skill_overrides(["git-ops"], ["pptx-author", "web-search"])
    assert ov["pptx-author"] == "off"
    assert ov["web-search"] == "off"
    assert ov["git-ops"] == "on"


def test_apply_claude_skill_overrides_writes_settings(tmp_path: Path, isolated_home: Path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")
    apply_claude_skill_overrides(
        path, build_claude_skill_overrides(["git-ops"], ["pptx-author"])
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["Bash"]
    assert data["skillOverrides"]["pptx-author"] == "off"
    assert data["skillOverrides"]["git-ops"] == "on"


def test_claude_hook_hard_default_writes_overrides(
    skills_root: Path,
    isolated_home: Path,
    adapters_root: Path,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.delenv("JEV_FILTER_MODE", raising=False)
    monkeypatch.setenv(
        "PYTHONPATH",
        str(repo_root / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    cwd = tmp_path / "proj"
    cwd.mkdir()
    payload = json.dumps(
        {
            "prompt": "rebase my branch and open a PR",
            "cwd": str(cwd),
            "hook_event_name": "UserPromptSubmit",
        }
    )
    script = adapters_root / "claude_code" / "hook.py"
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
    out = json.loads(proc.stdout)
    hso = out.get("hookSpecificOutput") or {}
    assert not hso.get("additionalContext")

    settings = cwd / ".claude" / "settings.local.json"
    assert settings.is_file()
    data = json.loads(settings.read_text(encoding="utf-8"))
    overrides = data["skillOverrides"]
    assert overrides.get("git-ops") == "on"
    dropped_off = [k for k, v in overrides.items() if v == "off"]
    assert dropped_off


def test_handle_stdin_hard_claude_library(skills_root: Path, isolated_home: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.setenv("JEV_FILTER_MODE", "hard")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    payload = {
        "prompt": "create a powerpoint pitch deck",
        "cwd": str(cwd),
        "hook_event_name": "UserPromptSubmit",
    }
    out = handle_user_prompt_submit_stdin(json.dumps(payload), host="claude_code")
    assert "additionalContext" not in (out.get("hookSpecificOutput") or {})
    settings = json.loads((cwd / ".claude" / "settings.local.json").read_text())
    assert settings["skillOverrides"]["pptx-author"] == "on"
    offs = {k for k, v in settings["skillOverrides"].items() if v == "off"}
    assert offs
    assert "pptx-author" not in offs


def test_codex_skills_config_toml_omits_enabled_skills():
    text = render_codex_skills_config_toml(["pptx-author", "web-search"])
    assert 'name = "pptx-author"' in text
    assert "enabled = false" in text
    assert "git-ops" not in text


def test_apply_codex_skills_config(tmp_path: Path, isolated_home: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(isolated_home))
    cfg = resolve_codex_config_path(home=isolated_home)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('model = "gpt-5"\n', encoding="utf-8")
    names = apply_codex_skills_config(cfg, ["pptx-author", "docker-compose"])
    assert names == ["pptx-author", "docker-compose"]
    text = cfg.read_text(encoding="utf-8")
    assert 'model = "gpt-5"' in text
    assert 'name = "pptx-author"' in text
    assert "enabled = false" in text
    apply_codex_skills_config(cfg, ["web-search"])
    text2 = cfg.read_text(encoding="utf-8")
    assert 'name = "web-search"' in text2
    assert 'name = "pptx-author"' not in text2


def test_codex_hook_hard_writes_config(
    skills_root: Path,
    isolated_home: Path,
    adapters_root: Path,
    repo_root: Path,
    monkeypatch,
):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.setenv("JEV_FILTER_MODE", "hard")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(repo_root / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    script = adapters_root / "codex" / "hook.py"
    payload = json.dumps(
        {
            "prompt": "rebase my branch and open a PR",
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
    cfg = isolated_home / ".codex" / "config.toml"
    assert cfg.is_file()
    text = cfg.read_text(encoding="utf-8")
    assert "enabled = false" in text
    assert 'name = "git-ops"' not in text


def test_hermes_xml_filter_removes_dropped():
    xml = (
        "<available_skills>\n"
        "  git:\n"
        "    - git-ops: rebase and PR\n"
        "    - pptx-author: slides\n"
        "    - web-search: search\n"
        "</available_skills>"
    )
    filtered = filter_available_skills_xml(xml, {"git-ops"})
    assert "git-ops" in filtered
    assert "pptx-author" not in filtered
    assert "web-search" not in filtered


def test_hermes_llm_request_hard_filter():
    req = {
        "model": "test",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Intro\n<available_skills>\n"
                    "    - git-ops: rebase\n"
                    "    - pptx-author: deck\n"
                    "</available_skills>\nOutro"
                ),
            },
            {"role": "user", "content": "rebase my branch"},
        ],
    }
    out = filter_hermes_llm_request(req, ["git-ops"])
    content = out["messages"][0]["content"]
    assert "git-ops" in content
    assert "pptx-author" not in content
    assert out["model"] == "test"


def test_hermes_on_llm_request_middleware(
    adapters_root: Path,
    repo_root: Path,
    skills_root: Path,
    isolated_home: Path,
    monkeypatch,
):
    import importlib.util

    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.setenv("JEV_FILTER_MODE", "hard")
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    path = adapters_root / "hermes" / "__init__.py"
    spec = importlib.util.spec_from_file_location("jev_hermes_hard", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    registered_mw: dict = {}
    registered_hooks: dict = {}

    class FakeCtx:
        def register_middleware(self, kind, fn):
            registered_mw[kind] = fn

        def register_hook(self, name, fn):
            registered_hooks[name] = fn

    mod.register(FakeCtx())
    assert "llm_request" in registered_mw
    assert "pre_llm_call" in registered_hooks

    soft = mod.on_pre_llm_call({"message": "rebase my branch and open a PR"})
    assert soft == {} or not soft.get("context")

    request = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "<available_skills>\n"
                    "    - git-ops: rebase\n"
                    "    - pptx-author: deck\n"
                    "    - web-search: search\n"
                    "</available_skills>"
                ),
            },
            {"role": "user", "content": "rebase my branch and open a PR"},
        ]
    }
    result = mod.on_llm_request(request=request)
    assert result is not None
    assert "request" in result
    content = result["request"]["messages"][0]["content"]
    assert "git-ops" in content
    assert "pptx-author" not in content


def test_selection_keeps_git_ops_for_hard_payloads(skills_root: Path, isolated_home: Path):
    outcome = run_selection(
        "rebase my branch and open a PR",
        host="claude_code",
        skill_roots=[skills_root],
        options=SelectionOptions(mode="local", threshold=0.1),
    )
    assert "git-ops" in outcome.result.kept_names
    dropped = set(outcome.result.dropped_names)
    assert dropped
    ov = build_claude_skill_overrides(outcome.result.kept_names, outcome.result.dropped_names)
    for name in dropped:
        assert ov[name] == "off"
