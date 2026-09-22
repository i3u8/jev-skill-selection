"""Jev-backed keep/drop: one Noul (or Choice) per skill vs the user message.

Differentiation from TypeSafe's skill-*suggestion* cookbook
(https://docs.typesafe.ai/cookbooks/skill_suggestion.md): that recipe picks
*at most one* skill name to hint to the agent. We independently keep/drop
*many* skills so only relevant SKILL.md bodies enter the prompt — a context
budget filter, not a single recommender.
"""

from __future__ import annotations

from typing import Any, Sequence

from .catalog import Skill
from .jev_client import JevClient, SystemOneResult
from .models import SelectionOptions, SkillDecision
from .local_mode import local_score_all


KEEP_NOUL_INSTRUCTIONS = (
    "Should the agent inject the skill described in `skill` into its prompt "
    "to handle the user's `message`? Answer yes only if the skill's documented "
    "purpose is directly useful for this specific request. Answer no if it is "
    "unrelated, only tangentially related, or would waste context."
)


def _excerpt(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)] + "…"


def _prefilter(
    message: str,
    catalog: Sequence[Skill],
    options: SelectionOptions,
    always_keep: set[str],
) -> tuple[list[Skill], list[SkillDecision]]:
    """Optionally shrink the set sent to Jev; always_keep always survives."""
    if not options.local_prefilter or len(catalog) <= options.local_prefilter_top_k:
        return list(catalog), []

    scored = local_score_all(message, catalog)
    top = scored[: options.local_prefilter_top_k]
    top_names = {s.name for s, _, _ in top} | always_keep
    candidates = [s for s in catalog if s.name in top_names]
    dropped_early: list[SkillDecision] = []
    for skill, score, _reason in scored[options.local_prefilter_top_k :]:
        if skill.name in always_keep:
            continue
        dropped_early.append(
            SkillDecision(
                name=skill.name,
                kept=False,
                score=round(score, 4),
                reason=f"local prefilter (outside top {options.local_prefilter_top_k})",
                char_count=skill.char_count,
            )
        )
    return candidates, dropped_early


def _build_noul_questions(
    candidates: Sequence[Skill],
    *,
    body_excerpt_chars: int,
) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for skill in candidates:
        qid = f"keep::{skill.name}"
        questions[qid] = {
            "type": "noul",
            "instructions": {
                "question": KEEP_NOUL_INSTRUCTIONS,
                "skill": {
                    "name": skill.name,
                    "description": skill.description,
                    "body_excerpt": _excerpt(skill.body, body_excerpt_chars),
                },
            },
            "criteria": {
                "true": "Skill is directly useful for the user's message",
                "false": "Skill is irrelevant or not worth the context cost",
            },
        }
    return questions


def _build_choice_questions(
    candidates: Sequence[Skill],
    *,
    body_excerpt_chars: int,
) -> dict[str, dict[str, Any]]:
    """Single Choice with keep/drop is awkward for N skills; instead we use
    one Choice whose options are skill names plus ``__none__``, then map
    probabilities to soft scores. Prefer ``noul`` strategy for true multi-keep.
    """
    criteria: dict[str, str | None] = {
        skill.name: f"{skill.description} — {_excerpt(skill.body, body_excerpt_chars)}"
        for skill in candidates
    }
    criteria["__none__"] = "None of these skills should be injected for this message."
    return {
        "which": {
            "type": "choice",
            "instructions": (
                "Which skill, if any, is most relevant to inject for the user's "
                "message? Prefer __none__ when nothing fits. Probabilities over "
                "skills will be used as soft keep scores."
            ),
            "criteria": criteria,
        }
    }


def _decisions_from_noul(
    candidates: Sequence[Skill],
    result: SystemOneResult,
    *,
    threshold: float,
    always_keep: set[str],
    always_drop: set[str],
    max_keep: int | None,
) -> list[SkillDecision]:
    by_name = {s.name: s for s in candidates}
    kept: list[SkillDecision] = []
    dropped: list[SkillDecision] = []

    for skill in candidates:
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
        answer = result.answers.get(f"keep::{skill.name}") or {}
        noul = float(answer.get("noul", 0.0))
        if skill.name in always_keep:
            kept.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=max(noul, 1.0),
                    reason="always_keep",
                    char_count=skill.char_count,
                )
            )
            continue
        if noul >= threshold:
            kept.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=round(noul, 4),
                    reason=f"jev noul={noul:.3f} >= {threshold}",
                    char_count=skill.char_count,
                )
            )
        else:
            dropped.append(
                SkillDecision(
                    name=skill.name,
                    kept=False,
                    score=round(noul, 4),
                    reason=f"jev noul={noul:.3f} < {threshold}",
                    char_count=skill.char_count,
                )
            )

    kept.sort(key=lambda d: (-d.score, d.name.lower()))
    if max_keep is not None and len(kept) > max_keep:
        always = [d for d in kept if d.reason == "always_keep"]
        rest = [d for d in kept if d.reason != "always_keep"]
        keep_n = max(0, max_keep - len(always))
        for d in rest[keep_n:]:
            dropped.append(
                SkillDecision(
                    name=d.name,
                    kept=False,
                    score=d.score,
                    reason=f"over max_keep={max_keep}",
                    char_count=by_name[d.name].char_count,
                )
            )
        kept = always + rest[:keep_n]
    return kept + dropped


def _decisions_from_choice(
    candidates: Sequence[Skill],
    result: SystemOneResult,
    *,
    threshold: float,
    always_keep: set[str],
    always_drop: set[str],
    max_keep: int | None,
) -> list[SkillDecision]:
    answer = result.answers.get("which") or {}
    probs = dict(answer.get("probabilities") or {})
    by_name = {s.name: s for s in candidates}
    kept: list[SkillDecision] = []
    dropped: list[SkillDecision] = []

    for skill in candidates:
        score = float(probs.get(skill.name, 0.0))
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
            kept.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=max(score, 1.0),
                    reason="always_keep",
                    char_count=skill.char_count,
                )
            )
            continue
        if score >= threshold:
            kept.append(
                SkillDecision(
                    name=skill.name,
                    kept=True,
                    score=round(score, 4),
                    reason=f"jev choice p={score:.3f} >= {threshold}",
                    char_count=skill.char_count,
                )
            )
        else:
            dropped.append(
                SkillDecision(
                    name=skill.name,
                    kept=False,
                    score=round(score, 4),
                    reason=f"jev choice p={score:.3f} < {threshold}",
                    char_count=skill.char_count,
                )
            )

    kept.sort(key=lambda d: (-d.score, d.name.lower()))
    if max_keep is not None and len(kept) > max_keep:
        always = [d for d in kept if d.reason == "always_keep"]
        rest = [d for d in kept if d.reason != "always_keep"]
        keep_n = max(0, max_keep - len(always))
        for d in rest[keep_n:]:
            dropped.append(
                SkillDecision(
                    name=d.name,
                    kept=False,
                    score=d.score,
                    reason=f"over max_keep={max_keep}",
                    char_count=by_name[d.name].char_count,
                )
            )
        kept = always + rest[:keep_n]
    return kept + dropped


def jev_decisions(
    message: str,
    catalog: Sequence[Skill],
    options: SelectionOptions,
    *,
    client: JevClient | None = None,
) -> tuple[list[SkillDecision], dict[str, Any]]:
    """Call Jev and return (decisions, raw meta)."""
    always_keep = set(options.always_keep)
    always_drop = set(options.always_drop)

    candidates, early_drop = _prefilter(message, catalog, options, always_keep)
    # Skills forced into always_drop need not hit the API.
    api_candidates = [s for s in candidates if s.name not in always_drop]
    forced_drop = [
        SkillDecision(
            name=s.name,
            kept=False,
            score=0.0,
            reason="always_drop",
            char_count=s.char_count,
        )
        for s in candidates
        if s.name in always_drop
    ]

    if not api_candidates:
        return early_drop + forced_drop, {"skipped_api": True, "reason": "no candidates"}

    jev = client or JevClient(
        api_key=options.api_key,
        base_url=options.base_url,
        model=options.model,
        timeout_seconds=options.timeout_seconds,
    )

    state = {"message": message}
    if options.jev_strategy == "choice":
        questions = _build_choice_questions(
            api_candidates, body_excerpt_chars=options.body_excerpt_chars
        )
        result = jev.system_one(state=state, questions=questions, model=options.model)
        decisions = _decisions_from_choice(
            api_candidates,
            result,
            threshold=options.threshold,
            always_keep=always_keep,
            always_drop=always_drop,
            max_keep=options.max_keep,
        )
    else:
        questions = _build_noul_questions(
            api_candidates, body_excerpt_chars=options.body_excerpt_chars
        )
        result = jev.system_one(state=state, questions=questions, model=options.model)
        decisions = _decisions_from_noul(
            api_candidates,
            result,
            threshold=options.threshold,
            always_keep=always_keep,
            always_drop=always_drop,
            max_keep=options.max_keep,
        )

    meta = {
        "model": result.model,
        "usage": result.usage,
        "strategy": options.jev_strategy,
        "candidate_count": len(api_candidates),
        "raw_answers": result.answers,
    }
    return decisions + early_drop + forced_drop, meta
