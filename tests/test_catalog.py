from __future__ import annotations

from pathlib import Path

from jev_skill_selection.catalog import load_catalog, parse_skill_md


def test_parse_skill_md_frontmatter():
    text = """---
name: demo
description: A demo skill
tags: [a, b]
---

# Body

Hello.
"""
    skill = parse_skill_md(text, path="/tmp/demo/SKILL.md")
    assert skill.name == "demo"
    assert skill.description == "A demo skill"
    assert skill.metadata.get("tags") == ["a", "b"]
    assert "Hello" in skill.body
    assert skill.char_count > 0


def test_load_catalog_closed_set(skills_root: Path):
    skills = load_catalog([skills_root])
    names = {s.name for s in skills}
    assert names == {
        "git-ops",
        "web-search",
        "pptx-author",
        "python-debug",
        "docker-compose",
    }
    assert all(s.path.endswith("SKILL.md") for s in skills)


def test_load_catalog_missing_root(tmp_path: Path):
    assert load_catalog([tmp_path / "nope"]) == []
