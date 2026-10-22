"""Triage application logs from the command line.

    python -m logtriage.cli app.log [more.log ...] [--report triage.md] [--fail-on-spike]
    kubectl logs deploy/shop-api --since=2h | python -m logtriage.cli -

Exit code 0 = no spikes (or --fail-on-spike not set), 1 = spike found with --fail-on-spike.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyze import TriageReport, analyse
from .parser import parse_lines


def render(report: TriageReport) -> str:
    out = ["# Log triage report", ""]
    if report.window_start:
        out.append(
            f"Analysed **{report.total_events}** log lines from {report.window_start:%Y-%m-%d %H:%M} "
            f"to {report.window_end:%H:%M}: **{report.total_errors}** errors, "
            f"**{len(report.spikes)}** spike(s)."
        )
    else:
        out.append("No parseable log lines found.")
    out.append("")

    for i, spike in enumerate(report.spikes, 1):
        out += [
            f"## Spike {i}: {spike.start:%H:%M} – {spike.end:%H:%M}",
            "",
            f"- Peak **{spike.peak_errors_per_min} errors/min** vs baseline {spike.baseline_errors_per_min} errors/min",
            f"- Services: {', '.join(f'{s} ({n})' for s, n in spike.services)}",
        ]
        if spike.top_signatures:
            sig, n = spike.top_signatures[0]
            total = sum(c for _, c in spike.top_signatures)
            share = n / total if total else 0
            new = " It first appeared during this spike." if sig in spike.new_signatures else ""
            out.append(f"- **Likely cause:** `{sig}` accounts for {share:.0%} of errors in this window.{new}")
        out += ["", "| Errors | Signature |", "|---:|---|"]
        out += [f"| {n} | `{sig}` |" for sig, n in spike.top_signatures]
        out.append("")

    if report.top_signatures:
        out += ["## Top error signatures overall", "", "| Errors | Signature |", "|---:|---|"]
        out += [f"| {n} | `{sig}` |" for sig, n in report.top_signatures]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="logtriage", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="log files, or - for stdin")
    parser.add_argument("--report", help="write the markdown report to this file")
    parser.add_argument("--baseline-minutes", type=int, default=15)
    parser.add_argument("--sigma", type=float, default=3.0)
    parser.add_argument("--min-errors", type=int, default=5, help="minimum errors/min to count as a spike")
    parser.add_argument("--fail-on-spike", action="store_true", help="exit 1 if any spike is found")
    args = parser.parse_args(argv)

    events = []
    for name in args.files:
        if name == "-":
            events.extend(parse_lines(sys.stdin))
        else:
            with open(name, errors="replace") as fh:
                events.extend(parse_lines(fh))

    report = analyse(events, args.baseline_minutes, args.sigma, args.min_errors)
    text = render(report)
    print(text)
    if args.report:
        Path(args.report).write_text(text)
    return 1 if (args.fail_on_spike and report.spikes) else 0


if __name__ == "__main__":
    sys.exit(main())
