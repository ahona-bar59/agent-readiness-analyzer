"""ARA command-line interface.

    ara analyze --input <file|glob> [--format all|json|markdown|pdf]
                [--out DIR] [--strict-gates/--no-strict-gates] [--mock]

Implemented with argparse (stdlib) so there is no dependency to install.
"""
from __future__ import annotations

import argparse
import glob
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import Settings
from .graph import analyze


def _read_inputs(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        if p.is_file():
            files.append(p)
            continue
        matched = [Path(m) for m in glob.glob(pat, recursive=True)]
        files.extend(m for m in matched if m.is_file())
    # De-dupe, keep order.
    seen, unique = set(), []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(f)
    return unique


def _analyze_one(path: Path, settings: Settings, out_dir: Path, fmt: str) -> dict:
    from .report import write_outputs

    text = path.read_text(encoding="utf-8", errors="replace")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    card, reasons, guard = analyze(text, settings, analyzed_at=stamp)
    written = write_outputs(card, out_dir, fmt, verdict_reasons=reasons)
    return {"card": card, "reasons": reasons, "guard": guard, "written": written, "src": path}


_VERDICT_MARK = {
    "DEPLOYABLE": "[DEPLOYABLE]",
    "CONDITIONAL": "[CONDITIONAL]",
    "NOT_DEPLOYABLE": "[NOT DEPLOYABLE]",
}


def _print_summary(res: dict, fmt: str) -> None:
    card = res["card"]
    guard = res["guard"]
    print("=" * 72)
    print(f"  {card.agent_name}")
    score_str = f"{card.total_score}/10" + (" (provisional)" if card.provisional else "")
    print(f"  {_VERDICT_MARK.get(card.verdict, card.verdict)}"
          f"   Score: {score_str}   Autonomy: {card.autonomy_level}"
          f"   ({card.scoring_mode} scoring)")
    comp = card.completeness
    if comp:
        print(f"  Input completeness: {comp.pct}% ({comp.tier})   "
              f"assessment confidence: {card.assessment_confidence}")
    missing_mandatory = [
        r for r in card.input_requirements if r.mandatory and r.status != "PRESENT"
    ]
    if card.provisional and missing_mandatory:
        print(f"  ! {len(missing_mandatory)} mandatory requirement(s) not documented "
              f"- client requirements doc generated to send back.")
    print("-" * 72)
    for d in card.dimensions:
        print(f"    {d.score:>3}/2  {d.name}")
    failed = [g for g in card.hard_gates if g.status == "FAIL"]
    if failed:
        print("  Hard gates FAILED:")
        for g in failed:
            print(f"    - {g.gate}: {g.evidence}")
    else:
        print("  Hard gates: all PASS")
    if guard.injection_hits:
        print(f"  ! Input guard flagged {len(guard.injection_hits)} injection pattern(s) "
              f"(conf {guard.injection_confidence:.2f}) - treated as data.")
    if guard.pii_masked:
        print(f"  ! Masked {guard.pii_masked} PII item(s) before scoring.")
    print("  Written:")
    for w in res["written"]:
        print(f"    - {w}")
    print("=" * 72)
    print()


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if args.strict_gates is not None:
        settings.strict_gates = args.strict_gates
    if args.mock:
        settings.force_mock = True
    if args.threshold is not None:
        settings.deploy_threshold = args.threshold

    files = _read_inputs(args.input)
    if not files:
        print(f"ARA: no input files matched {args.input}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    print(f"ARA v{__version__}  |  scoring mode: {settings.scoring_mode}  |  "
          f"strict gates: {settings.strict_gates}  |  {len(files)} file(s)\n")

    worst = "DEPLOYABLE"
    order = {"DEPLOYABLE": 0, "CONDITIONAL": 1, "NOT_DEPLOYABLE": 2}
    for path in files:
        res = _analyze_one(path, settings, out_dir, args.format)
        _print_summary(res, args.format)
        if order[res["card"].verdict] > order[worst]:
            worst = res["card"].verdict

    # Exit code: 0 deployable, 1 conditional, 2 not-deployable (useful for CI gating).
    return {"DEPLOYABLE": 0, "CONDITIONAL": 1, "NOT_DEPLOYABLE": 2}[worst]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ara",
        description="Agent Readiness Analyzer - score any agent for the QE Agentic Hub.",
    )
    p.add_argument("--version", action="version", version=f"ara {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Analyze one or more agent artifacts.")
    a.add_argument("--input", "-i", nargs="+", required=True,
                   help="File(s) or glob(s): README/spec/code of the agent(s).")
    a.add_argument("--format", "-f", default="all",
                   choices=["all", "json", "markdown", "html", "pdf"],
                   help="Output format (default: all). 'html' -> open in browser, Ctrl+P to save PDF.")
    a.add_argument("--out", "-o", default="reports", help="Output directory (default: reports).")
    a.add_argument("--threshold", type=float, default=None,
                   help="Override the deployable score cut-off (default 7.0).")
    a.add_argument("--mock", action="store_true",
                   help="Force the offline heuristic scorer even if LLM is configured.")
    strict = a.add_mutually_exclusive_group()
    strict.add_argument("--strict-gates", dest="strict_gates", action="store_true", default=None,
                        help="Enforce hard gates (default).")
    strict.add_argument("--no-strict-gates", dest="strict_gates", action="store_false",
                        help="Disable hard-gate overrides (score-only verdict).")
    a.set_defaults(func=cmd_analyze)
    return p


def main(argv: list[str] | None = None) -> int:
    # Make stdout UTF-8 safe on Windows consoles (cp1252 by default).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
