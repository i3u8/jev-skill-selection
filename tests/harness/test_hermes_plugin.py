from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


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
    registered_mw: dict = {}

    class FakeCtx:
        def register_hook(self, name, fn):
            registered[name] = fn

        def register_middleware(self, kind, fn):
            registered_mw[kind] = fn

    mod.register(FakeCtx())
    assert "pre_llm_call" in registered
    assert registered["pre_llm_call"] is mod.on_pre_llm_call
    assert "llm_request" in registered_mw
    assert registered_mw["llm_request"] is mod.on_llm_request


def test_hermes_on_pre_llm_call_soft_mode(
    adapters_root: Path,
    repo_root: Path,
    skills_root: Path,
    isolated_home: Path,
    monkeypatch,
):
    monkeypatch.setenv("JEV_SKILL_ROOTS", str(skills_root))
    monkeypatch.setenv("JEV_MODE", "local")
    monkeypatch.setenv("JEV_THRESHOLD", "0.1")
    monkeypatch.setenv("JEV_FILTER_MODE", "soft")
    mod = _load_hermes(adapters_root, repo_root)
    out = mod.on_pre_llm_call({"message": "rebase my branch and open a PR"})
    assert "context" in out
    assert "git-ops" in out["context"]


def test_hermes_register_hooks_dict_fallback(adapters_root: Path, repo_root: Path, isolated_home: Path):
    mod = _load_hermes(adapters_root, repo_root)
    ctx = SimpleNamespace(hooks={}, middleware={})
    mod.register(ctx)
    assert "pre_llm_call" in ctx.hooks
    assert "llm_request" in ctx.middleware
