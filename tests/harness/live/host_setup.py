"""Helpers to stage isolated HOME configs and invoke real host CLIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = REPO_ROOT / "adapters"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"
PROMPT = "rebase my branch and open a PR"


@dataclass
class HostRunResult:
    host: str
    installed: bool
    skip_reason: str | None
    returncode: int | None
    stdout: str
    stderr: str
    e2e_log_path: Path | None
    mock_log_path: Path | None
    mode: str  # local | jev
    cmd: list[str]


def which_host(name: str) -> str | None:
    return shutil.which(name)


def copy_fixture_skills(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for skill_dir in FIXTURES.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            target = dest / skill_dir.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(skill_dir, target)


def selection_mode() -> str:
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        return "jev"
    return "local"


def base_env(
    *,
    home: Path,
    mock_base: str,
    e2e_log: Path,
    skill_roots: list[Path],
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    # Isolated home — do not leak real user credentials into host CLIs.
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["CODEX_HOME"] = str(home / ".codex")
    env["HERMES_HOME"] = str(home / ".hermes")
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")

    mode = selection_mode()
    env["JEV_MODE"] = mode if mode == "jev" else "local"
    if mode != "jev":
        env.pop("TYPESAFE_API_KEY", None)
    env["JEV_THRESHOLD"] = env.get("JEV_THRESHOLD") or "0.1"
    env["JEV_SKILL_ROOTS"] = os.pathsep.join(str(p) for p in skill_roots)
    env["JEV_E2E_LOG"] = str(e2e_log)
    env["JEV_PYTHON"] = env.get("JEV_PYTHON") or shutil.which("python3") or "python3"
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    # Mock LLM — never hit real providers.
    env["ANTHROPIC_BASE_URL"] = mock_base
    env["ANTHROPIC_API_KEY"] = "sk-mock"
    env["ANTHROPIC_AUTH_TOKEN"] = "sk-mock"
    env["OPENAI_BASE_URL"] = mock_base.rstrip("/") + "/v1"
    env["OPENAI_API_KEY"] = "sk-mock"
    # Block accidental real spend if a host ignores base URL.
    env["ANTHROPIC_API_KEY"] = "sk-mock"

    # Prefer mock over OAuth keychains.
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    if extra:
        env.update(extra)
    return env


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def setup_claude(home: Path, project: Path, mock_base: str = "") -> Path:
    """Write Claude settings + skills; return settings path."""
    skills = home / ".claude" / "skills"
    copy_fixture_skills(skills)
    proj_skills = project / ".claude" / "skills"
    copy_fixture_skills(proj_skills)

    hook = ADAPTERS / "claude_code" / "hook.py"
    base = (mock_base or os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    settings = {
        "env": {
            "ANTHROPIC_BASE_URL": base,
            "ANTHROPIC_API_KEY": "sk-mock",
            "ANTHROPIC_AUTH_TOKEN": "sk-mock",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        },
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3",
                            "args": [str(hook)],
                            "timeout": 30,
                            "statusMessage": "jev-skill-selection e2e",
                        }
                    ]
                }
            ]
        },
        "permissions": {"defaultMode": "bypassPermissions"},
    }
    # User settings
    user_settings = home / ".claude" / "settings.json"
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    # Project settings (also load under -p without --bare)
    proj_settings = project / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True, exist_ok=True)
    proj_settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    # Trust / bypass dialogs for headless
    claude_json = home / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "hasCompletedOnboarding": True,
                "projects": {
                    str(project): {
                        "hasTrustDialogAccepted": True,
                        "hasAcceptedBypassPermissionsWarning": True,
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return user_settings


def setup_codex(home: Path, project: Path, mock_base: str) -> None:
    skills = home / ".agents" / "skills"
    copy_fixture_skills(skills)
    copy_fixture_skills(home / ".codex" / "skills")
    copy_fixture_skills(project / ".agents" / "skills")

    codex_home = home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    hook = ADAPTERS / "codex" / "hook.py"
    hooks = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hook}",
                            "timeout": 30,
                            "statusMessage": "jev-skill-selection e2e",
                        }
                    ]
                }
            ]
        }
    }
    (codex_home / "hooks.json").write_text(json.dumps(hooks, indent=2), encoding="utf-8")

    # Responses API only (chat wire_api retired). Point openai provider at mock.
    config = textwrap.dedent(
        f"""\
        model = "mock-model"
        openai_base_url = "{mock_base.rstrip('/')}/v1"
        model_provider = "mock"
        approval_policy = "never"
        sandbox_mode = "danger-full-access"

        [model_providers.mock]
        name = "Jev Mock LLM"
        base_url = "{mock_base.rstrip('/')}/v1"
        env_key = "OPENAI_API_KEY"
        wire_api = "responses"

        [features]
        hooks = true

        [projects."{project}"]
        trust_level = "trusted"
        """
    )
    (codex_home / "config.toml").write_text(config, encoding="utf-8")
    # Fake auth so Codex does not try ChatGPT login
    (codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "sk-mock", "tokens": None}),
        encoding="utf-8",
    )


def setup_hermes(home: Path, project: Path, mock_base: str) -> None:
    hermes_home = home / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    skills = hermes_home / "skills"
    copy_fixture_skills(skills)
    copy_fixture_skills(project / ".hermes" / "skills")

    plugins = hermes_home / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    link = plugins / "jev-skill-selection"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(ADAPTERS / "hermes")

    config = textwrap.dedent(
        f"""\
        model:
          default: mock-model
          provider: custom
          base_url: {mock_base.rstrip('/')}/v1
          api_key: sk-mock
        plugins:
          enabled:
            - jev-skill-selection
          disabled: []
        """
    )
    (hermes_home / "config.yaml").write_text(config, encoding="utf-8")
    (hermes_home / ".env").write_text(
        f"OPENAI_API_KEY=sk-mock\nOPENAI_BASE_URL={mock_base.rstrip('/')}/v1\n",
        encoding="utf-8",
    )


def setup_opencode(home: Path, project: Path, mock_base: str) -> None:
    xdg = home / ".config" / "opencode"
    xdg.mkdir(parents=True, exist_ok=True)
    plugins_dir = xdg / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    # Copy (not symlink) so Bun/Node can resolve relative imports cleanly.
    dest = plugins_dir / "jev-skill-selection.ts"
    dest.write_text((ADAPTERS / "opencode" / "index.ts").read_text(encoding="utf-8"), encoding="utf-8")

    proj_plugins = project / ".opencode" / "plugins"
    proj_plugins.mkdir(parents=True, exist_ok=True)
    (proj_plugins / "jev-skill-selection.ts").write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")

    copy_fixture_skills(project / ".opencode" / "skills")
    copy_fixture_skills(xdg / "skills")

    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "model": "mock/mock-model",
        "provider": {
            "mock": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Jev Mock LLM",
                "options": {
                    "baseURL": f"{mock_base.rstrip('/')}/v1",
                    "apiKey": "sk-mock",
                },
                "models": {"mock-model": {"name": "Mock Model"}},
            }
        },
    }
    (xdg / "opencode.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (project / "opencode.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def run_cmd(cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
    )
