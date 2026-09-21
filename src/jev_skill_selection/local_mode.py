"""Local keyword/metadata shortlist — no network, no API key."""

from __future__ import annotations

import re
from typing import Sequence

from .catalog import Skill
from .models import SkillDecision


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "for",
        "in",
        "on",
        "with",
        "is",
        "it",
        "this",
        "that",
        "be",
        "as",
        "at",
        "by",
        "from",
        "my",
        "me",
        "i",
        "you",
        "we",
        "please",
        "help",
        "can",
        "could",
        "would",
        "should",
        "how",
        "what",
        "when",
        "where",
        "which",
        "do",
        "does",
        "did",
        "just",
        "into",
        "using",
    }
)


def tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOP and len(t) > 1
    }


def _skill_tokens(skill: Skill) -> set[str]:
    parts = [skill.name.replace("-", " ").replace("_", " "), skill.description]
    tags = skill.metadata.get("tags") or skill.metadata.get("keywords")
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    elif isinstance(tags, str):
        parts.append(tags)
    # Light body signal without dumping the whole file into the bag.
    parts.append(skill.body[:800])
    return tokenize(" ".join(parts))


def score_skill(message: str, skill: Skill) -> tuple[float, str]:
    """Return (score 0..1, reason) for local relevance."""
    msg_tokens = tokenize(message)
    if not msg_tokens:
        return 0.0, "empty message tokens"

    skill_toks = _skill_tokens(skill)
    if not skill_toks:
        return 0.0, "empty skill tokens"

    overlap = msg_tokens & skill_toks
    name_bits = tokenize(skill.name.replace("-", " ").replace("_", " "))
    name_hits = msg_tokens & name_bits

    union = msg_tokens | skill_toks
    jaccard = len(overlap) / len(union) if union else 0.0
    name_bonus = 0.35 if name_hits else 0.0
    coverage = len(overlap) / len(msg_tokens)
    score = min(1.0, 0.55 * coverage + 0.25 * jaccard + name_bonus)

    if name_hits and overlap:
        reason = f"name+token overlap {sorted(overlap)[:8]}"
    elif name_hits:
        reason = f"name match {sorted(name_hits)}"
    elif overlap:
        reason = f"token overlap {sorted(overlap)[:8]}"
    else:
        reason = "no keyword overlap"
    return score, reason


def local_score_all(
    message: str, catalog: Sequence[Skill]
) -> list[tuple[Skill, float, str]]:
    scored: list[tuple[Skill, float, str]] = []
    for skill in catalog:
        score, reason = score_skill(message, skill)
        scored.append((skill, score, reason))
    scored.sort(key=lambda t: (-t[1], t[0].name.lower()))
    return scored


def local_decisions(
    message: str,
    catalog: Sequence[Skill],
    *,
    threshold: float,
    max_keep: int | None,
    always_keep: set[str],
    always_drop: set[str],
) -> list[SkillDecision]:
    """Score every skill and emit keep/drop decisions (closed set)."""
    scored = local_score_all(message, catalog)
    kept_ranked: list[SkillDecision] = []
    dropped: list[SkillDecision] = []

    for skill, score, reason in scored:
        if skill.name in always_drop:
            dropped.append(
                SkillDecision(
                    name=skill.name,
                    kept=False,
                    score=0.0,
                    reason="always_drop",
                    char_count=skill.char_count,
                )
            )
            continue
        if skill.name in always_keep:
            kept_ranked.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=max(round(score, 4), 1.0),
                    reason="always_keep",
                    char_count=skill.char_count,
                )
            )
            continue
        if score >= threshold:
            kept_ranked.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=round(score, 4),
                    reason=reason,
                    char_count=skill.char_count,
                )
            )
        else:
            dropped.append(
                SkillDecision(
                    name=skill.name,
                    kept=False,
                    score=round(score, 4),
                    reason=f"below threshold ({score:.3f} < {threshold})",
                    char_count=skill.char_count,
                )
            )

    if max_keep is not None and len(kept_ranked) > max_keep:
        always = [d for d in kept_ranked if d.reason == "always_keep"]
        rest = [d for d in kept_ranked if d.reason != "always_keep"]
        keep_n = max(0, max_keep - len(always))
        demoted = rest[keep_n:]
        kept_ranked = always + rest[:keep_n]
        for d in demoted:
            dropped.append(
                SkillDecision(
                    name=d.name,
                    kept=False,
                    score=d.score,
                    reason=f"over max_keep={max_keep}",
                    char_count=d.char_count,
                )
            )

    return kept_ranked + dropped
