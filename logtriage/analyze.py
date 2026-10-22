"""Bucket errors per minute, flag spikes against a rolling baseline, and rank the signatures behind them."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .parser import LogEvent


@dataclass
class Spike:
    start: datetime
    end: datetime
    peak_errors_per_min: int
    baseline_errors_per_min: float
    top_signatures: list[tuple[str, int]]
    services: list[tuple[str, int]]
    new_signatures: list[str]  # first seen during this spike


@dataclass
class TriageReport:
    total_events: int
    total_errors: int
    window_start: datetime | None
    window_end: datetime | None
    top_signatures: list[tuple[str, int]]
    spikes: list[Spike] = field(default_factory=list)


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def analyse(
    events: list[LogEvent],
    baseline_minutes: int = 15,
    sigma: float = 3.0,
    min_errors: int = 5,
    top_n: int = 5,
) -> TriageReport:
    """Flag minutes whose error count exceeds mean + sigma * stdev of the preceding baseline window.

    Consecutive spiking minutes are merged into one spike.
    """
    events = sorted(events, key=lambda e: e.ts)
    errors = [e for e in events if e.is_error]
    report = TriageReport(
        total_events=len(events),
        total_errors=len(errors),
        window_start=events[0].ts if events else None,
        window_end=events[-1].ts if events else None,
        top_signatures=Counter(e.signature for e in errors).most_common(top_n),
    )
    if not errors:
        return report

    per_minute: dict[datetime, list[LogEvent]] = defaultdict(list)
    for e in errors:
        per_minute[_minute(e.ts)].append(e)

    first, last = _minute(events[0].ts), _minute(events[-1].ts)
    minutes = []
    t = first
    while t <= last:
        minutes.append(t)
        t += timedelta(minutes=1)

    counts = [len(per_minute.get(m, [])) for m in minutes]
    first_seen: dict[str, datetime] = {}
    for e in errors:
        first_seen.setdefault(e.signature, e.ts)

    # Baseline = the last N *normal* minutes, so a long incident doesn't become its own baseline
    spiking: list[tuple[datetime, int, float]] = []
    normal_counts: list[int] = []
    for minute, count in zip(minutes, counts, strict=True):
        window = normal_counts[-baseline_minutes:]
        if len(window) < 3:
            normal_counts.append(count)
            continue
        mean = statistics.fmean(window)
        stdev = statistics.pstdev(window)
        threshold = max(min_errors, mean + sigma * max(stdev, 1.0))
        if count >= threshold:
            spiking.append((minute, count, mean))
        else:
            normal_counts.append(count)

    # Merge consecutive spiking minutes
    groups: list[list[tuple[datetime, int, float]]] = []
    for item in spiking:
        if groups and item[0] - groups[-1][-1][0] <= timedelta(minutes=1):
            groups[-1].append(item)
        else:
            groups.append([item])

    for group in groups:
        start, end = group[0][0], group[-1][0] + timedelta(minutes=1)
        in_spike = [e for e in errors if start <= e.ts < end]
        sigs = Counter(e.signature for e in in_spike)
        report.spikes.append(
            Spike(
                start=start,
                end=end,
                peak_errors_per_min=max(c for _, c, _ in group),
                baseline_errors_per_min=round(group[0][2], 2),
                top_signatures=sigs.most_common(top_n),
                services=Counter(e.service for e in in_spike).most_common(),
                new_signatures=[s for s in sigs if start <= first_seen[s] < end],
            )
        )
    return report
