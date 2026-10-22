"""Regression gate: compare current stats to a baseline using absolute limits and relative tolerances."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .results import EndpointStats


@dataclass
class GateConfig:
    # Absolute SLO-style limits (fail regardless of the baseline)
    max_p95_ms: float = 300.0
    max_error_rate: float = 0.01
    # Relative limits versus baseline
    p95_regression_pct: float = 15.0
    throughput_drop_pct: float = 20.0
    # Ignore endpoints with too few samples to be meaningful
    min_samples: int = 20

    @classmethod
    def from_file(cls, path: str | Path) -> GateConfig:
        return cls(**json.loads(Path(path).read_text()))


@dataclass
class Finding:
    label: str
    check: str
    passed: bool
    detail: str


@dataclass
class GateResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(f.passed for f in self.findings)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]


def _pct_change(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0 if current == 0 else float("inf")
    return (current - baseline) / baseline * 100


def evaluate(
    current: dict[str, EndpointStats],
    baseline: dict[str, dict] | None,
    config: GateConfig,
) -> GateResult:
    result = GateResult()
    for label, stats in current.items():
        if stats.samples < config.min_samples and label != "ALL":
            continue

        result.findings.append(
            Finding(
                label,
                "p95 within limit",
                stats.p95_ms <= config.max_p95_ms,
                f"p95 {stats.p95_ms:.0f} ms (limit {config.max_p95_ms:.0f} ms)",
            )
        )
        result.findings.append(
            Finding(
                label,
                "error rate within limit",
                stats.error_rate <= config.max_error_rate,
                f"errors {stats.error_rate:.2%} (limit {config.max_error_rate:.2%})",
            )
        )

        base = (baseline or {}).get(label)
        if not base:
            continue
        p95_change = _pct_change(stats.p95_ms, base["p95_ms"])
        result.findings.append(
            Finding(
                label,
                "p95 vs baseline",
                p95_change <= config.p95_regression_pct,
                f"p95 {base['p95_ms']:.0f} → {stats.p95_ms:.0f} ms ({p95_change:+.1f}%, "
                f"tolerance +{config.p95_regression_pct:.0f}%)",
            )
        )
        if label == "ALL":
            tput_change = _pct_change(stats.throughput_rps, base["throughput_rps"])
            result.findings.append(
                Finding(
                    label,
                    "throughput vs baseline",
                    tput_change >= -config.throughput_drop_pct,
                    f"throughput {base['throughput_rps']:.1f} → {stats.throughput_rps:.1f} req/s "
                    f"({tput_change:+.1f}%, tolerance -{config.throughput_drop_pct:.0f}%)",
                )
            )
    return result


def load_baseline(path: str | Path) -> dict[str, dict] | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def save_baseline(path: str | Path, stats: dict[str, EndpointStats]) -> None:
    Path(path).write_text(json.dumps({k: v.to_dict() for k, v in stats.items()}, indent=2) + "\n")
