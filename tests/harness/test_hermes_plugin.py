from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from jev_skill_selection.models import SelectionOptions


def _load_hermes(adapters_root: Path, repo_root: Path):
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    path = adapters_root / "hermes" / "__init__.py"
    spec = importlib.util.spec_from_file_location("jev_hermes_plugin_smoke", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hermes_register_smoke(adapters_root: Path, repo_root: Path, isolated_home: Path):
    mod = _load_hermes(adapters_root, repo_root)
    registered: dict = {}

    class FakeCtx:
        def register_hook(self, name, fn):
            registered[name] = fn

    mod.register(FakeCtx())
    assert "pre_llm_call" in registered
    assert registered["pre_llm_call"] is mod.on_pre_llm_call


def test_hermes_on_pre_llm_call_context(
    adapters_root: Path,
    repo_root: Path,
    skills_root: Path,
    isolated_home: Path,
    monkeypatch,
):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    mod = _load_hermes(adapters_root, repo_root)
    out = mod.on_pre_llm_call({"message": "rebase my branch and open a PR"})
    assert "context" in out
    assert "git-ops" in out["context"]


def test_hermes_register_hooks_dict_fallback(adapters_root: Path, repo_root: Path, isolated_home: Path):
    mod = _load_hermes(adapters_root, repo_root)
    ctx = SimpleNamespace(hooks={})
    # No register_hook attribute
    mod.register(ctx)
    assert "pre_llm_call" in ctx.hooks
