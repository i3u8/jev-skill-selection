"""Core API: ``select_skills(message, catalog, options) -> SelectionResult``."""

from __future__ import annotations

from typing import Sequence

from .catalog import Skill, catalog_char_total, skills_by_name
from .jev_client import JevClient
from .jev_mode import jev_decisions
from .local_mode import local_decisions
from .models import SelectionOptions, SelectionResult, SkillDecision


def select_skills(
    message: str,
    catalog: Sequence[Skill],
    options: SelectionOptions | None = None,
    *,
    client: JevClient | None = None,
) -> SelectionResult:
    """Decide which closed-set skills to keep in context for ``message``.

    Runs *before* the first model message so dropped skills never enter the prompt.

    Modes:
      - ``local``: keyword/metadata shortlist, no API key.
      - ``jev``: TypeSafe Jev Noul/Choice keep-or-drop (requires TYPESAFE_API_KEY).
    """
    opts = options or SelectionOptions()
    catalog_list = list(catalog)
    by_name = skills_by_name(catalog_list)
    chars_before = catalog_char_total(catalog_list)

    if opts.mode == "jev":
        decisions, raw = jev_decisions(message, catalog_list, opts, client=client)
        model = raw.get("model") or opts.model
    elif opts.mode == "local":
        decisions = local_decisions(
            message,
            catalog_list,
            threshold=opts.threshold,
            max_keep=opts.max_keep,
            always_keep=set(opts.always_keep),
            always_drop=set(opts.always_drop),
        )
        raw = {"strategy": "local_keyword"}
        model = None
    else:
        raise ValueError(f"Unknown mode: {opts.mode!r} (expected 'local' or 'jev')")

    # Ensure every catalog skill appears exactly once (closed set integrity).
    seen = {d.name for d in decisions}
    for skill in catalog_list:
        if skill.name not in seen:
            decisions.append(
                SkillDecision(
                    name=skill.name,
                    kept=False,
                    score=0.0,
                    reason="missing from scorer output",
                    char_count=skill.char_count,
                )
            )

    kept = [d for d in decisions if d.kept]
    dropped = [d for d in decisions if not d.kept]
    kept.sort(key=lambda d: (-d.score, d.name.lower()))
    dropped.sort(key=lambda d: (d.name.lower(),))

    for bucket in (kept, dropped):
        for i, d in enumerate(bucket):
            skill = by_name.get(d.name)
            if skill and d.char_count == 0:
                bucket[i] = SkillDecision(
                    name=d.name,
                    kept=d.kept,
                    score=d.score,
                    reason=d.reason,
                    char_count=skill.char_count,
                )

    chars_after = sum(d.char_count for d in kept)
    return SelectionResult(
        message=message,
        mode=opts.mode,
        kept=kept,
        dropped=dropped,
        chars_before=chars_before,
        chars_after=chars_after,
        chars_saved=max(0, chars_before - chars_after),
        model=model,
        raw=raw,
    )


def filter_catalog(
    catalog: Sequence[Skill],
    result: SelectionResult,
) -> list[Skill]:
    """Return catalog entries that were kept, in keep-score order."""
    by_name = skills_by_name(catalog)
    out: list[Skill] = []
    for d in result.kept:
        skill = by_name.get(d.name)
        if skill is not None:
            out.append(skill)
    return out
