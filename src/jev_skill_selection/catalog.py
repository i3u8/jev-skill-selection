"""Load a closed skill catalog from SKILL.md files with YAML-ish frontmatter."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>.*)\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class Skill:
    """One skill from a closed catalog (SKILL.md on disk)."""

    name: str
    description: str
    body: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """Rough prompt cost if this skill were fully injected."""
        # name + description + body + light markup overhead
        return len(self.name) + len(self.description) + len(self.body) + 64

    def index_line(self, max_desc: int = 120) -> str:
        desc = self.description.strip()
        if len(desc) > max_desc:
            desc = desc[: max_desc - 1] + "…"
        return f"{self.name}: {desc}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["char_count"] = self.char_count
        return d


def _parse_simple_yaml(block: str) -> dict[str, Any]:
    """Minimal YAML subset for SKILL.md frontmatter (no nested structures required).

    Supports ``key: value``, quoted strings, and simple lists as ``key: [a, b]``.
    Falls back to raw string values. Avoids requiring PyYAML.
    """
    meta: dict[str, Any] = {}
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = []
            if inner:
                for part in inner.split(","):
                    items.append(_unquote(part.strip()))
            meta[key] = items
        else:
            meta[key] = _unquote(value)
    return meta


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse_skill_md(text: str, path: str | Path | None = None) -> Skill:
    """Parse a SKILL.md document into a :class:`Skill`."""
    path_str = str(path) if path is not None else ""
    match = _FRONTMATTER_RE.match(text)
    if match:
        meta = _parse_simple_yaml(match.group("meta"))
        body = match.group("body").strip()
    else:
        meta = {}
        body = text.strip()

    name = str(meta.get("name") or "").strip()
    if not name and path is not None:
        # Parent directory name is a common SKILL.md convention.
        name = Path(path).parent.name
    if not name:
        name = Path(path_str).stem if path_str else "unnamed"

    description = str(meta.get("description") or "").strip()
    if not description:
        # First non-empty body line as a weak fallback.
        for line in body.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                description = line
                break

    # Keep name/description out of the opaque metadata bag for clarity.
    extra = {k: v for k, v in meta.items() if k not in {"name", "description"}}
    return Skill(
        name=name,
        description=description,
        body=body,
        path=path_str,
        metadata=extra,
    )


def load_catalog(
    roots: Sequence[str | Path],
    *,
    filename: str = "SKILL.md",
) -> list[Skill]:
    """Scan ``roots`` for ``SKILL.md`` files. Closed set only — no remote fetch.

    Duplicate names: later roots win (last write). Results are sorted by name.
    """
    by_name: dict[str, Skill] = {}
    for root in roots:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            continue
        if root_path.is_file() and root_path.name == filename:
            skill = parse_skill_md(root_path.read_text(encoding="utf-8"), root_path)
            by_name[skill.name] = skill
            continue
        for skill_path in sorted(root_path.rglob(filename)):
            if not skill_path.is_file():
                continue
            skill = parse_skill_md(skill_path.read_text(encoding="utf-8"), skill_path)
            by_name[skill.name] = skill
    return sorted(by_name.values(), key=lambda s: s.name.lower())


def catalog_char_total(skills: Iterable[Skill]) -> int:
    return sum(s.char_count for s in skills)


def skills_by_name(skills: Sequence[Skill]) -> dict[str, Skill]:
    return {s.name: s for s in skills}
