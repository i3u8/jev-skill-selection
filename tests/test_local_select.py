from __future__ import annotations

from pathlib import Path

from jev_skill_selection import SelectionOptions, load_catalog, select_skills


def test_local_keeps_relevant_drops_others(skills_root: Path):
    catalog = load_catalog([skills_root])
    result = select_skills(
        "Please open a pull request and fix my git commit history",
        catalog,
        SelectionOptions(mode="local", threshold=0.15),
    )
    assert result.mode == "local"
    assert "git-ops" in result.kept_names
    assert "pptx-author" in result.dropped_names or "pptx-author" not in result.kept_names
    assert result.chars_before >= result.chars_after
    assert result.chars_saved == result.chars_before - result.chars_after
    # Closed set: every skill appears once.
    assert len(result.kept) + len(result.dropped) == len(catalog)


def test_local_max_keep(skills_root: Path):
    catalog = load_catalog([skills_root])
    result = select_skills(
        "python pytest traceback docker compose containers",
        catalog,
        SelectionOptions(mode="local", threshold=0.05, max_keep=1),
    )
    assert len(result.kept) <= 1


def test_local_always_keep_drop(skills_root: Path):
    catalog = load_catalog([skills_root])
    result = select_skills(
        "unrelated hello world",
        catalog,
        SelectionOptions(
            mode="local",
            threshold=0.99,
            always_keep=("web-search",),
            always_drop=("git-ops",),
        ),
    )
    assert "web-search" in result.kept_names
    assert "git-ops" in result.dropped_names


def test_local_works_without_api_key(skills_root: Path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    catalog = load_catalog([skills_root])
    result = select_skills(
        "search the web for recent news",
        catalog,
        SelectionOptions(mode="local", threshold=0.1),
    )
    assert "web-search" in result.kept_names
