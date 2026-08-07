"""CLI: python -m evals run --suite reasoning_seed --model <tag>

Writes a JSON scorecard to ``evals/results/`` so runs can be diffed across
changes -- the baseline this whole package exists to produce.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .cases import available_suites, filter_cases, load_cases
from .runner import format_comparison, format_scorecard, run_suite
from .targets import build_target

RESULTS_DIR = Path(__file__).parent / "results"


def _run(args: argparse.Namespace) -> int:
    try:
        cases = load_cases(args.suite)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cases = filter_cases(cases, category=args.category, limit=args.limit)
    if not cases:
        print("error: no cases matched the filters", file=sys.stderr)
        return 2

    print(f"suite: {args.suite}  ({len(cases)} cases)")

    def progress(result) -> None:
        if args.quiet:
            return
        mark = "ok  " if result.correct else ("ERR " if result.error else "MISS")
        detail = result.error or f"got={result.extracted!r} want={result.expected!r}"
        print(f"  [{mark}] {result.case_id:<14} {result.latency_ms / 1000:>6.1f}s  {detail}")

    try:
        target = build_target("local", model=args.model)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"\nrunning local target ({target.model})...")
    local = run_suite(target, cases, on_case=progress)
    print("\n" + format_scorecard(local))

    reference = None
    if args.compare:
        try:
            ref_target = build_target("claude", model=args.compare_model)
        except RuntimeError as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            return 2
        print(f"\nrunning reference target ({ref_target.model})...")
        reference = run_suite(ref_target, cases, on_case=progress)
        print("\n" + format_scorecard(reference))
        print("\ncomparison:")
        print(format_comparison(local, reference))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite,
        "cases": len(cases),
        "label": args.label,
        "local": local.to_dict(include_results=True),
    }
    if reference is not None:
        payload["reference"] = reference.to_dict(include_results=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{args.label}-" if args.label else ""
    out = RESULTS_DIR / f"{slug}{args.suite}-{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nscorecard written to {out}")
    return 0


def _suites(_: argparse.Namespace) -> int:
    names = available_suites()
    if not names:
        print("no bundled suites found")
        return 1
    for name in names:
        cases = load_cases(name)
        cats = sorted({c.category for c in cases})
        print(f"{name}  ({len(cases)} cases: {', '.join(cats)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="score a suite against a target")
    run.add_argument("--suite", default="reasoning_seed",
                     help="bundled suite name or path to a .jsonl file")
    run.add_argument("--model", default="",
                     help="local model tag (default: $OBRENNA_EVAL_MODEL)")
    run.add_argument("--category", default=None, help="only run one category")
    run.add_argument("--limit", type=int, default=None, help="cap number of cases")
    run.add_argument("--compare", action="store_true",
                     help="also run the Claude reference target and print a diff")
    run.add_argument("--compare-model", default="claude-opus-5",
                     help="reference model id (default: claude-opus-5)")
    run.add_argument("--label", default="", help="tag the scorecard filename")
    run.add_argument("--quiet", action="store_true", help="suppress per-case lines")
    run.set_defaults(func=_run)

    suites = sub.add_parser("suites", help="list bundled suites")
    suites.set_defaults(func=_suites)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
