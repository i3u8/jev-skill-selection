from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REQUIRED = {
    "claude_code": ["hook.py", "settings.example.json", "README.md"],
    "codex": ["hook.py", "hooks.example.json", "README.md"],
    "hermes": ["plugin.yaml", "__init__.py", "README.md"],
    "opencode": ["index.ts", "package.json", "README.md"],
}


def test_adapter_files_exist(adapters_root: Path):
    for name, files in REQUIRED.items():
        base = adapters_root / name
        assert base.is_dir(), f"missing adapter dir {name}"
        for f in files:
            assert (base / f).is_file(), f"missing {name}/{f}"


def test_claude_settings_json_valid(adapters_root: Path):
    data = json.loads((adapters_root / "claude_code" / "settings.example.json").read_text())
    assert "hooks" in data
    assert "UserPromptSubmit" in data["hooks"]
    hooks = data["hooks"]["UserPromptSubmit"]
    assert isinstance(hooks, list) and hooks
    inner = hooks[0]["hooks"][0]
    assert inner["type"] == "command"
    blob = " ".join(inner.get("args") or []) + " " + str(inner.get("command", ""))
    assert "hook.py" in blob


def test_codex_hooks_json_valid(adapters_root: Path):
    data = json.loads((adapters_root / "codex" / "hooks.example.json").read_text())
    assert "UserPromptSubmit" in data["hooks"]


def test_hermes_plugin_yaml_valid(adapters_root: Path):
    path = adapters_root / "hermes" / "plugin.yaml"
    text = path.read_text(encoding="utf-8")
    assert "name: jev-skill-selection" in text or 'name: "jev-skill-selection"' in text
    assert "entry:" in text
    assert "pre_llm_call" in text
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        assert data["name"] == "jev-skill-selection"
        assert data.get("entry") == "__init__.py"
        assert "pre_llm_call" in (data.get("hooks") or [])
    except ImportError:
        pass  # structural string checks above are enough offline


def test_opencode_package_json_valid(adapters_root: Path):
    data = json.loads((adapters_root / "opencode" / "package.json").read_text())
    assert data["name"]
    assert "main" in data or "exports" in data


def test_hook_scripts_importable(adapters_root: Path, repo_root: Path):
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    for rel in ("claude_code/hook.py", "codex/hook.py"):
        path = adapters_root / rel
        spec = importlib.util.spec_from_file_location(rel.replace("/", "_").replace(".", "_"), path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "main", None))

    hermes = adapters_root / "hermes" / "__init__.py"
    spec = importlib.util.spec_from_file_location("jev_hermes_plugin", hermes)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.register)
    assert callable(mod.on_pre_llm_call)
