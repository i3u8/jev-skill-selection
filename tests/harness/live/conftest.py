from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .host_setup import REPO_ROOT, selection_mode

LIVE = os.environ.get("JEV_HARNESS_LIVE", "").strip() == "1"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: real host CLI e2e (requires JEV_HARNESS_LIVE=1)")


@pytest.fixture(scope="session")
def live_gate():
    if not LIVE:
        pytest.skip("JEV_HARNESS_LIVE!=1 — live host e2e disabled (offline default)")
    return True


@pytest.fixture(scope="session")
def mock_llm(tmp_path_factory, live_gate):
    """Start mock LLM server for the session; yield (base_url, log_path)."""
    port = _free_port()
    log_path = tmp_path_factory.mktemp("mock_llm") / "requests.jsonl"
    log_path.write_text("", encoding="utf-8")
    script = REPO_ROOT / "tests" / "harness" / "live" / "mock_llm_server.py"
    proc = subprocess.Popen(
        [sys.executable, str(script), "--host", "127.0.0.1", "--port", str(port), "--log", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    last_err = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"mock LLM exited early: {out}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError as exc:
            last_err = str(exc)
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError(f"mock LLM failed to bind: {last_err}")

    # Health check
    import urllib.request

    with urllib.request.urlopen(base + "/health", timeout=5) as resp:
        assert resp.status == 200

    yield {"base_url": base, "log_path": log_path, "port": port, "proc": proc}

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def live_workspace(tmp_path, mock_llm, monkeypatch):
    """Isolated HOME + project cwd for one host run.

    Prefer a workspace cache path over system ``/tmp`` — Codex refuses to
    create helper binaries when ``CODEX_HOME`` is under a temporary dir.
    """
    base = Path("/workspace/jev-skill-selection/.cache/live_e2e") / tmp_path.name
    base.mkdir(parents=True, exist_ok=True)
    home = base / "home"
    home.mkdir(exist_ok=True)
    project = base / "project"
    project.mkdir(exist_ok=True)
    # Minimal git repo so hosts that expect git do not fail loudly.
    subprocess.run(["git", "init"], cwd=project, check=False, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e2e@example.com"], cwd=project, check=False, capture_output=True)
    subprocess.run(["git", "config", "user.name", "e2e"], cwd=project, check=False, capture_output=True)
    (project / "README.md").write_text("# e2e\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=project, check=False, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=False, capture_output=True)

    e2e_log = base / "jev_e2e.jsonl"
    e2e_log.write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    return {
        "home": home,
        "project": project,
        "base": base,
        "e2e_log": e2e_log,
        "mock_base": mock_llm["base_url"],
        "mock_log": mock_llm["log_path"],
        "mode": selection_mode(),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
