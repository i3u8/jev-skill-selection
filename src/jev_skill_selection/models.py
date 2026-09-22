"""Shared dataclasses for catalog entries and selection results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Mode = Literal["local", "jev"]


@dataclass(frozen=True)
class SkillDecision:
    """Keep/drop decision for one skill."""

    name: str
    kept: bool
    score: float
    reason: str
    char_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectionOptions:
    """Runtime knobs for :func:`select_skills`."""

    mode: Mode = "local"
    # Keep skills whose score is >= threshold (0..1).
    threshold: float = 0.45
    # Soft cap on how many skills to keep (None = no cap beyond threshold).
    max_keep: int | None = None
    # Always keep these names regardless of score (still closed-set).
    always_keep: tuple[str, ...] = ()
    # Always drop these names.
    always_drop: tuple[str, ...] = ()
    # Jev model id. Pin a version for reproducibility; verify against
    # https://docs.typesafe.ai/models.md — default may lag aliases.
    model: str = "jev-1.13.0"
    # Prefer one Noul per skill (parallel, absolute keep/drop) vs a single Choice.
    jev_strategy: Literal["noul", "choice"] = "noul"
    # Optional pre-filter with local keyword scoring before calling Jev (saves tokens).
    local_prefilter: bool = True
    local_prefilter_top_k: int = 32
    # Inject skill body excerpt length into Jev criteria (chars).
    body_excerpt_chars: int = 400
    # API key / base URL; if None, read from TYPESAFE_API_KEY / TYPESAFE_BASE_URL.
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectionResult:
    """Outcome of a selection pass."""

    message: str
    mode: Mode
    kept: list[SkillDecision] = field(default_factory=list)
    dropped: list[SkillDecision] = field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0
    chars_saved: int = 0
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def kept_names(self) -> list[str]:
        return [d.name for d in self.kept]

    @property
    def dropped_names(self) -> list[str]:
        return [d.name for d in self.dropped]

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "mode": self.mode,
            "kept": [d.to_dict() for d in self.kept],
            "dropped": [d.to_dict() for d in self.dropped],
            "kept_names": self.kept_names,
            "dropped_names": self.dropped_names,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "chars_saved": self.chars_saved,
            "model": self.model,
            "raw": self.raw,
        }
