"""CLI: ``python -m jev_skill_selection catalog|select ...``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .catalog import load_catalog
from .models import SelectionOptions
from .select import select_skills


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jev-skill-selection",
        description=(
            "Filter which agent skills enter the prompt before the first LLM call. "
            "Keep/drop many skills for context size — not a single-skill suggester."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    cat = sub.add_parser("catalog", help="Scan roots for SKILL.md and list the closed set")
    cat.add_argument(
        "--root",
        action="append",
        dest="roots",
        required=True,
        help="Skill root directory (repeatable)",
    )
    cat.add_argument("--json", action="store_true", help="Emit JSON")

    sel = sub.add_parser("select", help="Keep/drop skills for a user message")
    sel.add_argument(
        "--root",
        action="append",
        dest="roots",
        required=True,
        help="Skill root directory (repeatable)",
    )
    sel.add_argument(
        "--message",
        "-m",
        required=True,
        help="User message to score skills against",
    )
    sel.add_argument(
        "--mode",
        choices=("local", "jev"),
        default="local",
        help="local = keyword shortlist (no key); jev = TypeSafe API",
    )
    sel.add_argument("--threshold", type=float, default=0.45)
    sel.add_argument("--max-keep", type=int, default=None)
    sel.add_argument(
        "--model",
        default="jev-1.13.0",
        help="Jev model id (default jev-1.13.0 — verify on docs.typesafe.ai)",
    )
    sel.add_argument(
        "--strategy",
        choices=("noul", "choice"),
        default="noul",
        dest="jev_strategy",
    )
    sel.add_argument("--always-keep", action="append", default=[], dest="always_keep")
    sel.add_argument("--always-drop", action="append", default=[], dest="always_drop")
    sel.add_argument("--no-prefilter", action="store_true")
    sel.add_argument("--json", action="store_true", help="Emit JSON")

    return p


def _cmd_catalog(args: argparse.Namespace) -> int:
    skills = load_catalog(args.roots)
    if args.json:
        print(json.dumps([s.to_dict() for s in skills], ensure_ascii=False, indent=2))
        return 0
    if not skills:
        print("No SKILL.md files found.", file=sys.stderr)
        return 1
    total = sum(s.char_count for s in skills)
    print(f"{len(skills)} skills ({total} chars rough):")
    for s in skills:
        desc = s.description[:80]
        print(f"  - {s.name}: {desc}  [{s.char_count} chars]  ({s.path})")
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    skills = load_catalog(args.roots)
    if not skills:
        print("No SKILL.md files found.", file=sys.stderr)
        return 1
    options = SelectionOptions(
        mode=args.mode,
        threshold=args.threshold,
        max_keep=args.max_keep,
        always_keep=tuple(args.always_keep or ()),
        always_drop=tuple(args.always_drop or ()),
        model=args.model,
        jev_strategy=args.jev_strategy,
        local_prefilter=not args.no_prefilter,
    )
    result = select_skills(args.message, skills, options)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(
        f"mode={result.mode}  model={result.model or '-'}  "
        f"kept={len(result.kept)}  dropped={len(result.dropped)}  "
        f"chars {result.chars_before} -> {result.chars_after} "
        f"(saved {result.chars_saved})"
    )
    print("kept:")
    for d in result.kept:
        print(f"  + {d.name}  score={d.score:.3f}  {d.reason}")
    print("dropped:")
    for d in result.dropped:
        print(f"  - {d.name}  score={d.score:.3f}  {d.reason}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "catalog":
        return _cmd_catalog(args)
    if args.command == "select":
        return _cmd_select(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
