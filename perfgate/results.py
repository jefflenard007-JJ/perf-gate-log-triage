"""Read load test results (JMeter JTL CSV or k6 summary JSON) into per-endpoint statistics."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class EndpointStats:
    label: str
    samples: int
    error_rate: float  # 0..1
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_rps: float

    def to_dict(self) -> dict:
        return asdict(self)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (the method JMeter's aggregate report uses)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _summarise(label: str, elapsed: list[float], errors: int, duration_s: float) -> EndpointStats:
    n = len(elapsed)
    return EndpointStats(
        label=label,
        samples=n,
        error_rate=round(errors / n, 4) if n else 0.0,
        p50_ms=percentile(elapsed, 50),
        p95_ms=percentile(elapsed, 95),
        p99_ms=percentile(elapsed, 99),
        throughput_rps=round(n / duration_s, 2) if duration_s > 0 else 0.0,
    )


def read_jtl(path: str | Path) -> dict[str, EndpointStats]:
    """Parse a JMeter JTL file saved as CSV with a header row.

    Uses the standard columns: timeStamp (ms epoch), elapsed (ms), label, success (true/false).
    Adds an "ALL" row covering every sample.
    """
    by_label: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    first_ts, last_ts = math.inf, -math.inf

    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        missing = {"timeStamp", "elapsed", "label", "success"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"JTL file is missing columns: {sorted(missing)}")
        for row in reader:
            label = row["label"]
            elapsed = float(row["elapsed"])
            ts = float(row["timeStamp"])
            first_ts = min(first_ts, ts)
            last_ts = max(last_ts, ts + elapsed)
            by_label.setdefault(label, []).append(elapsed)
            if row["success"].strip().lower() != "true":
                errors[label] = errors.get(label, 0) + 1

    if not by_label:
        raise ValueError(f"no samples found in {path}")

    duration_s = (last_ts - first_ts) / 1000
    stats = {
        label: _summarise(label, values, errors.get(label, 0), duration_s) for label, values in sorted(by_label.items())
    }
    all_values = [v for values in by_label.values() for v in values]
    stats["ALL"] = _summarise("ALL", all_values, sum(errors.values()), duration_s)
    return stats


def read_k6_summary(path: str | Path) -> dict[str, EndpointStats]:
    """Parse the JSON written by `k6 run --summary-export=summary.json`.

    k6's summary is overall rather than per endpoint, so this returns a single "ALL" row.
    Requires `summaryTrendStats` to include p(50), p(95) and p(99) (set in the k6 script).
    """
    data = json.loads(Path(path).read_text())
    metrics = data["metrics"]
    duration = metrics["http_req_duration"]
    reqs = metrics["http_reqs"]
    failed = metrics.get("http_req_failed", {})
    return {
        "ALL": EndpointStats(
            label="ALL",
            samples=int(reqs["count"]),
            error_rate=round(float(failed.get("value", 0.0)), 4),
            p50_ms=float(duration.get("p(50)", duration.get("med", 0.0))),
            p95_ms=float(duration["p(95)"]),
            p99_ms=float(duration.get("p(99)", 0.0)),
            throughput_rps=round(float(reqs["rate"]), 2),
        )
    }


def read_results(path: str | Path) -> dict[str, EndpointStats]:
    return read_k6_summary(path) if str(path).endswith(".json") else read_jtl(path)
