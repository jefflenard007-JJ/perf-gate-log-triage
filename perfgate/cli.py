"""Command line entry point.

    python -m perfgate.cli check results.jtl --baseline baselines/orders.json --report report.md
    python -m perfgate.cli check summary.json --baseline baselines/orders.json   # k6
    python -m perfgate.cli update-baseline results.jtl --baseline baselines/orders.json
    python -m perfgate.cli trend --db perf-history.db

Exit code 0 = pass, 1 = regression found (fails the CI job), 2 = bad input.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import history
from .gate import GateConfig, evaluate, load_baseline, save_baseline
from .results import read_results


def render_report(stats, result, baseline_found: bool) -> str:
    lines = [
        f"# Performance gate: {'PASSED' if result.passed else 'FAILED'}",
        "",
        "| Endpoint | Samples | Error rate | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (req/s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in stats.values():
        lines.append(
            f"| {s.label} | {s.samples} | {s.error_rate:.2%} | {s.p50_ms:.0f} | {s.p95_ms:.0f} "
            f"| {s.p99_ms:.0f} | {s.throughput_rps:.1f} |"
        )
    lines += ["", "## Checks", ""]
    for f in result.findings:
        lines.append(f"- {'✅' if f.passed else '❌'} **{f.label}**: {f.check}: {f.detail}")
    if not baseline_found:
        lines += ["", "_No baseline found: only absolute limits were checked._"]
    return "\n".join(lines) + "\n"


def cmd_check(args) -> int:
    stats = read_results(args.results)
    config = GateConfig.from_file(args.config) if args.config else GateConfig()
    baseline = load_baseline(args.baseline) if args.baseline else None
    result = evaluate(stats, baseline, config)
    report = render_report(stats, result, baseline is not None)
    print(report)
    if args.report:
        Path(args.report).write_text(report)
    if args.db:
        with history.connect(args.db) as conn:
            history.record_run(conn, stats, result.passed, os.getenv("CI_COMMIT_SHORT_SHA"))
    return 0 if result.passed else 1


def cmd_update_baseline(args) -> int:
    stats = read_results(args.results)
    save_baseline(args.baseline, stats)
    print(f"baseline written to {args.baseline}")
    return 0


def cmd_trend(args) -> int:
    with history.connect(args.db) as conn:
        rows = history.trend(conn, args.last)
    print(f"{'run_at':<26}{'commit':<10}{'endpoint':<24}{'p95 ms':>8}{'errors':>9}{'req/s':>8}")
    for run_at, sha, label, p95, err, tput in rows:
        print(f"{run_at:<26}{(sha or '-'):<10}{label:<24}{p95:>8.0f}{err:>9.2%}{tput:>8.1f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="perfgate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="evaluate a run; exit 1 on regression")
    check.add_argument("results", help="JMeter .jtl (CSV) or k6 summary .json")
    check.add_argument("--baseline", help="baseline JSON to compare against")
    check.add_argument("--config", help="gate thresholds JSON (defaults built in)")
    check.add_argument("--report", help="write a markdown report here")
    check.add_argument("--db", help="SQLite file to record the run in")
    check.set_defaults(func=cmd_check)

    upd = sub.add_parser("update-baseline", help="save this run as the new baseline")
    upd.add_argument("results")
    upd.add_argument("--baseline", required=True)
    upd.set_defaults(func=cmd_update_baseline)

    tr = sub.add_parser("trend", help="show recent runs from the history database")
    tr.add_argument("--db", required=True)
    tr.add_argument("--last", type=int, default=10)
    tr.set_defaults(func=cmd_trend)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"perfgate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
