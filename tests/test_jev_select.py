from __future__ import annotations

import json
from pathlib import Path

import pytest

from jev_skill_selection import SelectionOptions, load_catalog, select_skills
from jev_skill_selection.jev_client import JevClient, JevConfigError


def _fake_noul_opener(url, body, headers, timeout):
    payload = json.loads(body.decode("utf-8"))
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")
    assert "/v1/systemone" in url
    answers = {}
    for qid, q in payload["questions"].items():
        assert q["type"] == "noul"
        # Keep git-ops high, others low.
        name = qid.removeprefix("keep::")
        answers[qid] = {"type": "noul", "noul": 0.92 if name == "git-ops" else 0.05}
    return json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
    ).encode("utf-8")


def test_jev_noul_keep_drop_mocked(skills_root: Path):
    catalog = load_catalog([skills_root])
    client = JevClient(api_key="test-key", opener=_fake_noul_opener)
    result = select_skills(
        "help me rebase and open a PR",
        catalog,
        SelectionOptions(
            mode="jev",
            threshold=0.5,
            local_prefilter=False,
            model="jev-1.13.0",
        ),
        client=client,
    )
    assert result.mode == "jev"
    assert result.model == "jev-1.13.0"
    assert result.kept_names == ["git-ops"]
    assert "pptx-author" in result.dropped_names
    assert result.chars_saved > 0


def _fake_choice_opener(url, body, headers, timeout):
    payload = json.loads(body.decode("utf-8"))
    assert payload["questions"]["which"]["type"] == "choice"
    criteria = payload["questions"]["which"]["criteria"]
    probs = {k: 0.0 for k in criteria}
    probs["python-debug"] = 0.7
    probs["__none__"] = 0.3
    return json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": {
                "which": {
                    "type": "choice",
                    "choice": "python-debug",
                    "probabilities": probs,
                    "confidence": 0.5,
                }
            },
            "usage": {"input_tokens": 12, "output_tokens": 4},
        }
    ).encode("utf-8")


def test_jev_choice_strategy_mocked(skills_root: Path):
    catalog = load_catalog([skills_root])
    client = JevClient(api_key="test-key", opener=_fake_choice_opener)
    result = select_skills(
        "pytest is failing with a traceback",
        catalog,
        SelectionOptions(
            mode="jev",
            jev_strategy="choice",
            threshold=0.4,
            local_prefilter=False,
        ),
        client=client,
    )
    assert "python-debug" in result.kept_names


def test_jev_missing_api_key_errors(skills_root: Path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    catalog = load_catalog([skills_root])
    client = JevClient(api_key="")
    with pytest.raises(JevConfigError):
        select_skills(
            "anything",
            catalog,
            SelectionOptions(mode="jev", local_prefilter=False),
            client=client,
        )


def test_no_network_in_unit_tests(skills_root: Path):
    """Guard: jev path must use injected opener; we never call real urllib here."""
    catalog = load_catalog([skills_root])

    def boom(*_a, **_k):
        raise AssertionError("network should not be used in unit tests")

    client = JevClient(api_key="x", opener=boom)
    with pytest.raises(AssertionError, match="network"):
        select_skills(
            "git pr",
            catalog,
            SelectionOptions(mode="jev", local_prefilter=False),
            client=client,
        )
