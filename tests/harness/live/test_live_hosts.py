"""Real host CLI e2e with mocked LLM and optional real Jev.

Gate: ``JEV_HARNESS_LIVE=1``. Offline ``pytest`` skips this module via the
``live_gate`` fixture / skip markers.

Assertions (per host that runs):
1. Adapter hook executed (``JEV_E2E_LOG`` marker)
2. Keep set includes ``git-ops``
3. Mock LLM received a request *after* the hook (ordering by timestamps)
4. Soft inject: mock request body contains keep/drop or kept skill text
5. OpenCode hard filter: if skill tool description is observable in the mock
   request, dropped skills are absent
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from .host_setup import (
    PROMPT,
    base_env,
    read_jsonl,
    run_cmd,
    setup_claude,
    setup_codex,
    setup_hermes,
    setup_opencode,
    which_host,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("JEV_HARNESS_LIVE", "").strip() != "1",
        reason="JEV_HARNESS_LIVE!=1 — live host e2e disabled",
    ),
]


def _assert_common(host: str, *, e2e_log: Path, mock_log: Path, mode: str) -> dict:
    e2e = read_jsonl(e2e_log)
    assert e2e, f"{host}: hook did not write JEV_E2E_LOG marker ({e2e_log})"
    last = e2e[-1]
    assert last.get("marker") == "jev_skill_selection_hook_executed"
    assert last.get("host") in (host, host.replace("-", "_"))
    kept = last.get("kept_names") or []
    assert "git-ops" in kept, f"{host}: expected git-ops in keep set, got {kept} (mode={mode})"

    mock_reqs = read_jsonl(mock_log)
    assert mock_reqs, f"{host}: mock LLM received no requests"

    hook_ts = float(last.get("ts") or 0)
    after = [r for r in mock_reqs if float(r.get("ts") or 0) >= hook_ts - 0.05]
    assert after, (
        f"{host}: no mock LLM request at/after hook ts={hook_ts}; "
        f"mock count={len(mock_reqs)} first_ts={mock_reqs[0].get('ts')}"
    )

    # Soft inject: somewhere in a post-hook request we should see keep/drop guidance
    # or at least github/git-ops skill text when soft-inject is the mechanism.
    soft_hits = []
    for r in after:
        roles = r.get("roles") or {}
        blob = json.dumps(r.get("body") or {}, ensure_ascii=False)
        if (
            roles.get("saw_skills_context")
            or "jev-skill-selection" in blob
            or "KEPT:" in blob
            or "git-ops" in blob
        ):
            soft_hits.append(r)
    # Soft inject is host-dependent; Claude/Codex/Hermes/OpenCode all soft-inject.
    # If the host failed to forward additionalContext into the LLM payload we still
    # require hook+ordering above; soft inject is asserted when observable.
    return {
        "e2e": last,
        "mock_after": after,
        "soft_hits": soft_hits,
        "kept": kept,
        "dropped": last.get("dropped_names") or [],
    }


def test_live_claude_code(live_workspace):
    if not which_host("claude"):
        pytest.skip("claude CLI not installed on PATH")

    ws = live_workspace
    setup_claude(ws["home"], ws["project"], ws["mock_base"])
    # Truncate mock log so ordering is per-test
    ws["mock_log"].write_text("", encoding="utf-8")
    ws["e2e_log"].write_text("", encoding="utf-8")

    env = base_env(
        home=ws["home"],
        mock_base=ws["mock_base"],
        e2e_log=ws["e2e_log"],
        skill_roots=[ws["home"] / ".claude" / "skills", ws["project"] / ".claude" / "skills"],
        extra={
            # Ensure settings env block is not the only source
            "ANTHROPIC_BASE_URL": ws["mock_base"],
            "ANTHROPIC_API_KEY": "sk-mock",
        },
    )
    # Do NOT use --bare (skips hooks). Use -p non-interactive + skip permissions.
    cmd = [
        "claude",
        "-p",
        PROMPT,
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
        "--model",
        "claude-haiku-4-5-20251001",
    ]
    t0 = time.time()
    proc = run_cmd(cmd, env=env, cwd=ws["project"], timeout=180)
    summary = {
        "host": "claude_code",
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-1500:],
        "stderr_tail": proc.stderr[-1500:],
        "elapsed": time.time() - t0,
        "mode": ws["mode"],
    }
    (ws["project"] / "claude_e2e_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if proc.returncode != 0 and not read_jsonl(ws["e2e_log"]):
        pytest.fail(
            "claude live run failed before hook executed:\n"
            f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )

    info = _assert_common("claude_code", e2e_log=ws["e2e_log"], mock_log=ws["mock_log"], mode=ws["mode"])
    assert info["soft_hits"], (
        "claude: soft inject not observed in mock LLM body "
        "(additionalContext may not have been forwarded — check settings/hooks)"
    )


def test_live_codex(live_workspace):
    if not which_host("codex"):
        pytest.skip("codex CLI not installed on PATH")

    ws = live_workspace
    setup_codex(ws["home"], ws["project"], ws["mock_base"])
    ws["mock_log"].write_text("", encoding="utf-8")
    ws["e2e_log"].write_text("", encoding="utf-8")

    env = base_env(
        home=ws["home"],
        mock_base=ws["mock_base"],
        e2e_log=ws["e2e_log"],
        skill_roots=[
            ws["home"] / ".agents" / "skills",
            ws["home"] / ".codex" / "skills",
            ws["project"] / ".agents" / "skills",
        ],
    )
    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "-m",
        "mock-model",
        "-c",
        f'model_provider="mock"',
        "-c",
        f'openai_base_url="{ws["mock_base"].rstrip("/")}/v1"',
        PROMPT,
    ]
    proc = run_cmd(cmd, env=env, cwd=ws["project"], timeout=180)
    if proc.returncode != 0 and not read_jsonl(ws["e2e_log"]):
        pytest.fail(
            "codex live run failed before hook executed:\n"
            f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    info = _assert_common("codex", e2e_log=ws["e2e_log"], mock_log=ws["mock_log"], mode=ws["mode"])
    assert info["soft_hits"], "codex: soft inject not observed in mock LLM body"


def test_live_hermes(live_workspace):
    if not which_host("hermes"):
        pytest.skip("hermes CLI not installed on PATH")

    ws = live_workspace
    setup_hermes(ws["home"], ws["project"], ws["mock_base"])
    ws["mock_log"].write_text("", encoding="utf-8")
    ws["e2e_log"].write_text("", encoding="utf-8")

    env = base_env(
        home=ws["home"],
        mock_base=ws["mock_base"],
        e2e_log=ws["e2e_log"],
        skill_roots=[ws["home"] / ".hermes" / "skills", ws["project"] / ".hermes" / "skills"],
        extra={
            "HERMES_HOME": str(ws["home"] / ".hermes"),
            "OPENAI_BASE_URL": ws["mock_base"].rstrip("/") + "/v1",
            "OPENAI_API_KEY": "sk-mock",
        },
    )
    # One-shot non-interactive. --yolo bypasses approvals; --provider custom uses config base_url.
    cmd = [
        "hermes",
        "-z",
        PROMPT,
        "--provider",
        "custom",
        "-m",
        "mock-model",
        "--yolo",
        "--accept-hooks",
    ]
    proc = run_cmd(cmd, env=env, cwd=ws["project"], timeout=180)
    if proc.returncode != 0 and not read_jsonl(ws["e2e_log"]):
        # Document remaining blockers honestly rather than faking success.
        pytest.fail(
            "hermes live run failed before plugin hook executed:\n"
            f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    info = _assert_common("hermes", e2e_log=ws["e2e_log"], mock_log=ws["mock_log"], mode=ws["mode"])
    assert info["soft_hits"], "hermes: soft inject not observed in mock LLM body"


def test_live_opencode(live_workspace):
    if not which_host("opencode"):
        pytest.skip("opencode CLI not installed on PATH")

    ws = live_workspace
    setup_opencode(ws["home"], ws["project"], ws["mock_base"])
    ws["mock_log"].write_text("", encoding="utf-8")
    ws["e2e_log"].write_text("", encoding="utf-8")

    env = base_env(
        home=ws["home"],
        mock_base=ws["mock_base"],
        e2e_log=ws["e2e_log"],
        skill_roots=[
            ws["project"] / ".opencode" / "skills",
            ws["home"] / ".config" / "opencode" / "skills",
        ],
        extra={
            "OPENCODE_CONFIG": str(ws["project"] / "opencode.json"),
        },
    )
    cmd = [
        "opencode",
        "run",
        PROMPT,
        "-m",
        "mock/mock-model",
        "--auto",
        "--format",
        "json",
    ]
    proc = run_cmd(cmd, env=env, cwd=ws["project"], timeout=180)
    if proc.returncode != 0 and not read_jsonl(ws["e2e_log"]):
        pytest.fail(
            "opencode live run failed before plugin hook executed:\n"
            f"rc={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    info = _assert_common("opencode", e2e_log=ws["e2e_log"], mock_log=ws["mock_log"], mode=ws["mode"])
    # Soft inject
    assert info["soft_hits"], "opencode: soft inject not observed in mock LLM body"

    # Hard filter (optional observability): when a skill tool schema enumerates
    # available_skills in the mock request, dropped names must not remain there.
    dropped = set(info["dropped"])
    for r in info["mock_after"]:
        body = r.get("body") or {}
        blob = json.dumps(body, ensure_ascii=False)
        if "available_skills" not in blob and "availableSkills" not in blob:
            continue
        # Walk tools / schemas for skill-list arrays
        def _skill_names(obj):
            found = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("available_skills", "availableSkills") and isinstance(v, list):
                        for s in v:
                            found.append(s if isinstance(s, str) else (s or {}).get("name"))
                    else:
                        found.extend(_skill_names(v))
            elif isinstance(obj, list):
                for i in obj:
                    found.extend(_skill_names(i))
            return [n for n in found if n]
        listed = set(_skill_names(body))
        if listed:
            leak = dropped & listed
            assert not leak, f"opencode hard filter leaked dropped skills in tool schema: {leak}"
